#!/usr/bin/env python3
"""Validate CSVs, stage them in S3, and bulk-load Amazon Redshift.

``jsonToCsv.py`` is the only producer of ``<schema>/records.csv``. This loader
validates that contract locally, uploads a short-lived load batch to Amazon S3,
uses Redshift COPY, then calls the set-based procedures in
``db/functions_v1.sql``. It never derives marketplace release dates:
``data_snapshot`` and ``data_snapshot_detail`` for non-GSMArena records must
be blank and are copied from the matched ``original.central_info`` row by SQL.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import date
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlparse
from uuid import uuid4


LOG = logging.getLogger("csvToDataBase")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV_ROOT = PROJECT_ROOT / "filestorage" / "csvs"
SCHEMA_ORDER = (
    "original",
    "daraz",
    "mymobile",
    "mega",
    "whatamobile",
    "whatmobile",
)
RECORD_FIELDS = (
    "record_key",
    "source_schema",
    "source_site",
    "source_file",
    "source_url",
    "url_recovery",
    "data_snapshot",
    "data_snapshot_detail",
    "snapshot_source",
    "mobile_name",
    "network_2g",
    "network_3g",
    "network_4g",
    "network_5g",
    "launch_announced",
    "launch_status",
    "body_dimensions",
    "body_weight",
    "body_build",
    "body_sim",
    "body_protection",
    "display_type",
    "display_size",
    "display_resolution",
    "display_protection",
    "platform_os",
    "platform_chipset",
    "platform_cpu",
    "platform_gpu",
    "memory_card_slot",
    "memory_types_json",
    "memory_technology",
    "main_camera_specifications_json",
    "main_camera_features",
    "main_camera_video_json",
    "selfie_camera_specifications_json",
    "selfie_camera_features",
    "selfie_camera_video_json",
    "sound_loudspeaker",
    "sound_cable_jack",
    "features_wlan",
    "features_bluetooth",
    "features_positioning",
    "features_nfc",
    "features_infrared_port",
    "features_radio",
    "features_usb",
    "features_back_finger_print",
    "features_side_finger_print",
    "features_in_display_finger_print",
    "features_sensors",
    "battery_capacity",
    "battery_wireless_charging",
    "battery_charging_json",
    "colors_json",
    "exposure_weight",
    "prices_json",
    "completeness_score",
    "file_sha256",
    "payload_json",
)
JSON_FIELDS = (
    "memory_types_json",
    "main_camera_specifications_json",
    "main_camera_video_json",
    "selfie_camera_specifications_json",
    "selfie_camera_video_json",
    "battery_charging_json",
    "colors_json",
    "prices_json",
    "payload_json",
)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_DETAIL_RE = re.compile(
    r"^(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?$"
)
IAM_ROLE_RE = re.compile(r"^arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@_/-]+$")


class LoadValidationError(ValueError):
    """A local contract violation that must not reach Redshift."""


@dataclass(frozen=True)
class ValidationReport:
    validated_records: int
    records_by_schema: dict[str, int]
    explicit_master_mappings: int
    record_files: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "validated_records": self.validated_records,
            "records_by_schema": self.records_by_schema,
            "explicit_master_mappings": self.explicit_master_mappings,
            "record_files": self.record_files,
        }


def normalize_schema(value: str) -> str:
    schema = value.strip().lower()
    if schema not in SCHEMA_ORDER:
        raise LoadValidationError(f"unsupported source_schema {value!r}")
    return schema


def validate_url(value: str) -> str:
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise LoadValidationError(f"invalid source_url {value!r}")
    return cleaned


def validate_hash(value: str, field: str) -> str:
    cleaned = value.strip().lower()
    if not HASH_RE.fullmatch(cleaned):
        raise LoadValidationError(f"{field} must be a SHA-256 hex digest")
    return cleaned


def validate_json(value: str, field: str) -> None:
    try:
        json.loads(value)
    except json.JSONDecodeError as exc:
        raise LoadValidationError(f"{field} contains invalid JSON: {exc}") from exc


def validate_original_snapshot(row: Mapping[str, str]) -> None:
    try:
        year = int(row["data_snapshot"])
    except (TypeError, ValueError) as exc:
        raise LoadValidationError(
            "GSMArena data_snapshot must be a four-digit year"
        ) from exc
    if year < 1900 or year > 2100:
        raise LoadValidationError("GSMArena data_snapshot is outside 1900..2100")
    detail = row["data_snapshot_detail"].strip()
    if not SNAPSHOT_DETAIL_RE.fullmatch(detail):
        raise LoadValidationError(
            "GSMArena data_snapshot_detail must be MM or MM-DD"
        )
    if len(detail) == 5:
        month, day = (int(part) for part in detail.split("-"))
        try:
            date(year, month, day)
        except ValueError as exc:
            raise LoadValidationError(
                "GSMArena data_snapshot_detail is not a calendar date"
            ) from exc
    if row["snapshot_source"].strip() not in {
        "announced",
        "status",
        "current_utc",
    }:
        raise LoadValidationError("invalid GSMArena snapshot_source")


def validate_marketplace_snapshot(row: Mapping[str, str]) -> None:
    if row["data_snapshot"].strip() or row["data_snapshot_detail"].strip():
        raise LoadValidationError(
            "marketplace snapshots must be blank; Redshift inherits them from original"
        )
    if row["snapshot_source"].strip() != "original_database":
        raise LoadValidationError(
            "marketplace snapshot_source must be original_database"
        )


def validate_row(
    row: dict[str, str], expected_schema: str, path: Path, line_number: int
) -> dict[str, str]:
    try:
        schema = normalize_schema(row["source_schema"])
        if schema != expected_schema:
            raise LoadValidationError(
                f"source_schema {schema!r} does not match directory {expected_schema!r}"
            )
        row["source_schema"] = schema
        row["source_url"] = validate_url(row["source_url"])
        row["record_key"] = validate_hash(row["record_key"], "record_key")
        row["file_sha256"] = validate_hash(row["file_sha256"], "file_sha256")
        if not row["mobile_name"].strip():
            raise LoadValidationError("mobile_name is required")
        for field in JSON_FIELDS:
            validate_json(row[field], field)
        if schema == "original":
            validate_original_snapshot(row)
        else:
            validate_marketplace_snapshot(row)
        return row
    except (KeyError, LoadValidationError) as exc:
        raise LoadValidationError(f"{path}:{line_number}: {exc}") from exc


def discover_record_files(csv_root: Path, selected: set[str] | None) -> list[Path]:
    if not csv_root.is_dir():
        raise FileNotFoundError(f"CSV root does not exist: {csv_root}")
    paths = [
        csv_root / schema / "records.csv"
        for schema in SCHEMA_ORDER
        if selected is None or schema in selected
    ]
    paths = [path for path in paths if path.is_file()]
    if not paths:
        raise FileNotFoundError(
            f"No <schema>/records.csv files were found beneath {csv_root}"
        )
    return paths


def iter_rows(path: Path) -> Iterator[dict[str, str]]:
    expected_schema = normalize_schema(path.parent.name)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        missing = set(RECORD_FIELDS) - set(fields)
        if missing:
            raise LoadValidationError(
                f"{path} is missing required columns: {sorted(missing)}"
            )
        for line_number, source_row in enumerate(reader, start=2):
            row = {field: source_row.get(field, "") for field in RECORD_FIELDS}
            yield validate_row(row, expected_schema, path, line_number)


def load_master_map(path: Path | None) -> tuple[list[dict[str, str]], int]:
    if path is None:
        return [], 0
    rows: list[dict[str, str]] = []
    seen: dict[tuple[str, str], int] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"source_schema", "source_url", "product_id"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise LoadValidationError(
                f"{path} is missing master-map columns: {sorted(missing)}"
            )
        for line_number, source_row in enumerate(reader, start=2):
            try:
                schema = normalize_schema(source_row["source_schema"])
                if schema == "original":
                    raise LoadValidationError("original does not need a mapping")
                url = validate_url(source_row["source_url"])
                product_id = int(source_row["product_id"])
                if product_id <= 0:
                    raise LoadValidationError("product_id must be positive")
                key = (schema, url)
                if key in seen and seen[key] != product_id:
                    raise LoadValidationError(
                        f"conflicting mapping for {schema} {url}"
                    )
                if key in seen:
                    continue
                seen[key] = product_id
                rows.append(
                    {
                        "source_schema": schema,
                        "source_url": url,
                        "product_id": str(product_id),
                    }
                )
            except (KeyError, TypeError, ValueError, LoadValidationError) as exc:
                raise LoadValidationError(f"{path}:{line_number}: {exc}") from exc
    return rows, len(seen)


def materialize_batch(
    paths: Sequence[Path],
    directory: Path,
    limit: int | None,
    master_map: Sequence[Mapping[str, str]],
) -> tuple[ValidationReport, list[Path], Path | None]:
    counts: dict[str, int] = defaultdict(int)
    seen: set[tuple[str, str]] = set()
    staged: list[Path] = []
    total = 0
    stop = False
    for path in paths:
        if stop:
            break
        schema = path.parent.name
        destination = directory / schema / "records.csv"
        destination.parent.mkdir(parents=True, exist_ok=True)
        wrote = 0
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RECORD_FIELDS)
            writer.writeheader()
            for row in iter_rows(path):
                identity = (row["source_schema"], row["source_url"])
                if identity in seen:
                    raise LoadValidationError(
                        f"duplicate source_schema/source_url in input: {identity}"
                    )
                seen.add(identity)
                writer.writerow(row)
                total += 1
                wrote += 1
                counts[schema] += 1
                if limit is not None and total >= limit:
                    stop = True
                    break
        if wrote:
            staged.append(destination)
        else:
            destination.unlink()

    map_path: Path | None = None
    if master_map:
        map_path = directory / "product_map.csv"
        with map_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("source_schema", "source_url", "product_id"),
            )
            writer.writeheader()
            writer.writerows(master_map)
    report = ValidationReport(
        validated_records=total,
        records_by_schema=dict(sorted(counts.items())),
        explicit_master_mappings=len(master_map),
        record_files=[str(path) for path in paths],
    )
    return report, staged, map_path


def parse_s3_uri(value: str) -> tuple[str, str]:
    parsed = urlparse(value.strip())
    if parsed.scheme != "s3" or not parsed.netloc:
        raise LoadValidationError("--s3-uri must use s3://bucket/optional-prefix")
    return parsed.netloc, parsed.path.strip("/")


def sql_literal(value: str) -> str:
    if "\x00" in value:
        raise LoadValidationError("SQL literal contains a null byte")
    return "'" + value.replace("'", "''") + "'"


def copy_sql(table: str, s3_uri: str, iam_role: str, region: str) -> str:
    if table not in {"staging.phone_records", "staging.product_map"}:
        raise LoadValidationError(f"COPY table is not allowlisted: {table}")
    if not IAM_ROLE_RE.fullmatch(iam_role):
        raise LoadValidationError("invalid Redshift COPY IAM role ARN")
    parse_s3_uri(s3_uri)
    if not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", region):
        raise LoadValidationError(f"invalid AWS region {region!r}")
    return (
        f"COPY {table} FROM {sql_literal(s3_uri)} "
        f"IAM_ROLE {sql_literal(iam_role)} REGION {sql_literal(region)} "
        "FORMAT AS CSV IGNOREHEADER 1 EMPTYASNULL BLANKSASNULL "
        "ACCEPTINVCHARS TRIMBLANKS"
    )


def import_boto3() -> Any:
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "S3 staging requires boto3; install requirements.txt"
        ) from exc
    return boto3


def import_redshift_connector() -> Any:
    try:
        import redshift_connector  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Redshift loading requires redshift-connector; install requirements.txt"
        ) from exc
    return redshift_connector


def upload_batch(
    files: Sequence[Path],
    map_path: Path | None,
    s3_uri: str,
    region: str,
    run_token: str,
) -> tuple[list[tuple[str, str]], str | None, Any, list[tuple[str, str]]]:
    bucket, base_prefix = parse_s3_uri(s3_uri)
    client = import_boto3().client("s3", region_name=region)
    uploaded: list[tuple[str, str]] = []
    record_uris: list[tuple[str, str]] = []
    for path in files:
        schema = path.parent.name
        key = "/".join(
            part
            for part in (base_prefix, "loads", run_token, schema, "records.csv")
            if part
        )
        client.upload_file(str(path), bucket, key)
        uploaded.append((bucket, key))
        record_uris.append((schema, f"s3://{bucket}/{key}"))
    map_uri: str | None = None
    if map_path is not None:
        key = "/".join(
            part
            for part in (
                base_prefix,
                "loads",
                run_token,
                "product_map.csv",
            )
            if part
        )
        client.upload_file(str(map_path), bucket, key)
        uploaded.append((bucket, key))
        map_uri = f"s3://{bucket}/{key}"
    return uploaded, map_uri, client, record_uris


def connection_parameters(args: argparse.Namespace) -> dict[str, Any]:
    values = {
        "host": args.host or os.environ.get("REDSHIFT_HOST"),
        "database": args.database or os.environ.get("REDSHIFT_DATABASE"),
        "user": args.user or os.environ.get("REDSHIFT_USER"),
        "password": args.password or os.environ.get("REDSHIFT_PASSWORD"),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing Redshift connection settings: "
            + ", ".join(f"REDSHIFT_{name.upper()}" for name in missing)
        )
    return {
        **values,
        "port": args.port,
        "ssl": True,
        "timeout": args.connect_timeout,
    }


def load_redshift(
    args: argparse.Namespace,
    record_uris: Sequence[tuple[str, str]],
    map_uri: str | None,
) -> None:
    connector = import_redshift_connector()
    with connector.connect(**connection_parameters(args)) as connection:
        connection.autocommit = False
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'staging' AND table_name = 'phone_records'"
            )
            if int(cursor.fetchone()[0]) != 1:
                raise RuntimeError(
                    "staging.phone_records is missing; apply db/schema_v1.sql and "
                    "db/functions_v1.sql first"
                )
            cursor.execute("TRUNCATE TABLE staging.phone_records")
            cursor.execute("TRUNCATE TABLE staging.product_map")
            if map_uri:
                cursor.execute(
                    copy_sql(
                        "staging.product_map",
                        map_uri,
                        args.iam_role,
                        args.aws_region,
                    )
                )
            for schema, uri in record_uris:
                LOG.info("COPY %s from %s", schema, uri)
                cursor.execute(
                    copy_sql(
                        "staging.phone_records",
                        uri,
                        args.iam_role,
                        args.aws_region,
                    )
                )
            cursor.execute("CALL etl.load_all()")
        connection.commit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate CSVs and bulk-load them into Amazon Redshift."
    )
    parser.add_argument("--csv-root", type=Path, default=DEFAULT_CSV_ROOT)
    parser.add_argument(
        "--schema",
        action="append",
        choices=SCHEMA_ORDER,
        default=[],
        help="Load only this schema (repeatable).",
    )
    parser.add_argument(
        "--master-map",
        type=Path,
        help="Optional reviewed CSV: source_schema,source_url,product_id.",
    )
    parser.add_argument("--limit", type=int, help="Stage at most this many rows.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate selected rows without AWS credentials or a database connection.",
    )
    parser.add_argument(
        "--s3-uri",
        default=os.environ.get("REDSHIFT_S3_URI"),
        help="Private staging prefix, e.g. s3://bucket/mobile-info (or REDSHIFT_S3_URI).",
    )
    parser.add_argument(
        "--iam-role",
        default=os.environ.get("REDSHIFT_IAM_ROLE"),
        help="IAM role ARN attached to Redshift and allowed to read the S3 prefix.",
    )
    parser.add_argument(
        "--aws-region",
        default=os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1",
    )
    parser.add_argument("--host")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("REDSHIFT_PORT", "5439")),
    )
    parser.add_argument("--database")
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("--connect-timeout", type=int, default=30)
    parser.add_argument(
        "--keep-s3-staging",
        action="store_true",
        help="Keep this loader's exact temporary S3 objects after completion.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.port <= 0 or args.port > 65535:
        parser.error("--port must be between 1 and 65535")

    uploaded: list[tuple[str, str]] = []
    s3_client: Any | None = None
    try:
        selected = set(args.schema) if args.schema else None
        paths = discover_record_files(args.csv_root.resolve(), selected)
        master_rows, mapping_count = load_master_map(
            args.master_map.resolve() if args.master_map else None
        )
        with tempfile.TemporaryDirectory(prefix="mobileinfo-redshift-") as temporary:
            report, files, map_path = materialize_batch(
                paths,
                Path(temporary),
                args.limit,
                master_rows,
            )
            report = ValidationReport(
                report.validated_records,
                report.records_by_schema,
                mapping_count,
                report.record_files,
            )
            if args.dry_run:
                print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
                return 0
            if report.validated_records == 0:
                raise LoadValidationError("selected CSV files contain no rows")
            if not args.s3_uri:
                raise RuntimeError("--s3-uri or REDSHIFT_S3_URI is required")
            if not args.iam_role:
                raise RuntimeError("--iam-role or REDSHIFT_IAM_ROLE is required")
            run_token = uuid4().hex
            uploaded, map_uri, s3_client, record_uris = upload_batch(
                files,
                map_path,
                args.s3_uri,
                args.aws_region,
                run_token,
            )
            load_redshift(args, record_uris, map_uri)
            LOG.info(
                "Redshift load complete: rows=%d schemas=%s",
                report.validated_records,
                ",".join(report.records_by_schema),
            )
        return 0
    except Exception as exc:
        LOG.error("Redshift load failed: %s", exc)
        if args.log_level == "DEBUG":
            LOG.exception("Detailed failure")
        return 1
    finally:
        if uploaded and s3_client is not None and not args.keep_s3_staging:
            for bucket, key in uploaded:
                try:
                    s3_client.delete_object(Bucket=bucket, Key=key)
                except Exception as exc:
                    LOG.warning(
                        "Could not remove temporary s3://%s/%s: %s",
                        bucket,
                        key,
                        exc,
                    )


if __name__ == "__main__":
    sys.exit(main())
