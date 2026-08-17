#!/usr/bin/env python3
"""Load ``jsonToCsv.py`` records into PostgreSQL safely and idempotently.

The target may be Supabase PostgreSQL, ordinary PostgreSQL, AWS
RDS/Aurora PostgreSQL, or Azure Database for PostgreSQL.  All writes go through
the versioned ``api.ingest_<schema>`` functions in ``db/functions_v1.sql``;
the loader never assembles table names from untrusted CSV values.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import islice
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlparse


LOG = logging.getLogger("csvToDataBase")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV_ROOT = PROJECT_ROOT / "filestorage" / "csvs"

SCHEMA_FUNCTIONS = {
    "original": "api.ingest_original",
    "daraz": "api.ingest_daraz",
    "mymobile": "api.ingest_mymobile",
    "mega": "api.ingest_mega",
    "whatamobile": "api.ingest_whatamobile",
    "whatmobile": "api.ingest_whatmobile",
}
SCHEMA_ORDER = tuple(SCHEMA_FUNCTIONS)
REQUIRED_COLUMNS = {
    "record_key",
    "source_schema",
    "source_file",
    "source_url",
    "data_snapshot",
    "file_sha256",
    "payload_json",
}
FAILURE_FIELDS = [
    "record_key",
    "source_schema",
    "source_file",
    "source_url",
    "error_type",
    "error_message",
]


class LoadValidationError(ValueError):
    """A malformed staging row that must not reach the database."""


@dataclass(frozen=True)
class LoadRecord:
    record_key: str
    source_schema: str
    source_file: str
    source_url: str
    data_snapshot: str
    file_sha256: str
    payload_json: str
    master_product_id: int | None

    def parameters(self) -> tuple[Any, ...]:
        common: tuple[Any, ...] = (
            self.payload_json,
            self.source_url,
            self.data_snapshot,
            self.source_file,
        )
        if self.source_schema == "original":
            return common
        return common + (self.master_product_id,)


def normalize_site_schema(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SCHEMA_FUNCTIONS:
        raise LoadValidationError(f"Unsupported source_schema {value!r}")
    return normalized


def validate_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise LoadValidationError(f"Invalid data_snapshot {value!r}") from exc
    if parsed.tzinfo is None:
        raise LoadValidationError("data_snapshot must include a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def validate_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise LoadValidationError(f"Invalid source_url {value!r}")
    return value.strip()


def validate_payload(value: str) -> str:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise LoadValidationError(f"payload_json is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LoadValidationError("payload_json must contain a JSON object")
    if not str(payload.get("MobileName") or "").strip():
        raise LoadValidationError("payload_json.MobileName is required")
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def load_master_map(path: Path | None) -> dict[tuple[str, str], int]:
    """Read explicit source-to-canonical mappings.

    Accepted columns are ``source_schema``, ``source_url``, and ``product_id``.
    Exact normalized-name matching still happens in SQL when a mapping is not
    provided; fuzzy matching is deliberately left for a reviewed later stage.
    """

    if path is None:
        return {}
    mappings: dict[tuple[str, str], int] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"source_schema", "source_url", "product_id"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise LoadValidationError(
                f"Master map {path} is missing columns: {sorted(missing)}"
            )
        for line_number, row in enumerate(reader, start=2):
            schema = normalize_site_schema(row["source_schema"])
            if schema == "original":
                raise LoadValidationError(
                    f"{path}:{line_number}: original does not need a master mapping"
                )
            url = validate_url(row["source_url"])
            try:
                product_id = int(row["product_id"])
            except (TypeError, ValueError) as exc:
                raise LoadValidationError(
                    f"{path}:{line_number}: product_id must be an integer"
                ) from exc
            if product_id <= 0:
                raise LoadValidationError(
                    f"{path}:{line_number}: product_id must be positive"
                )
            key = (schema, url)
            previous = mappings.get(key)
            if previous is not None and previous != product_id:
                raise LoadValidationError(
                    f"{path}:{line_number}: conflicting mapping for {schema} {url}"
                )
            mappings[key] = product_id
    return mappings


def discover_record_files(csv_root: Path, selected: set[str] | None) -> list[Path]:
    if not csv_root.is_dir():
        raise FileNotFoundError(f"CSV root does not exist: {csv_root}")
    paths: list[Path] = []
    for schema in SCHEMA_ORDER:
        if selected is not None and schema not in selected:
            continue
        path = csv_root / schema / "records.csv"
        if path.is_file():
            paths.append(path)
    if not paths:
        raise FileNotFoundError(
            f"No <schema>/records.csv files were found beneath {csv_root}"
        )
    return paths


def iter_load_records(
    paths: Iterable[Path],
    master_map: Mapping[tuple[str, str], int],
) -> Iterator[LoadRecord]:
    for path in paths:
        expected_schema = path.parent.name
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
            if missing:
                raise LoadValidationError(
                    f"{path} is missing required columns: {sorted(missing)}"
                )
            for line_number, row in enumerate(reader, start=2):
                try:
                    schema = normalize_site_schema(row["source_schema"])
                    if schema != expected_schema:
                        raise LoadValidationError(
                            f"source_schema {schema!r} does not match directory "
                            f"{expected_schema!r}"
                        )
                    record_key = row["record_key"].strip()
                    if len(record_key) != 64 or any(
                        character not in "0123456789abcdef"
                        for character in record_key.lower()
                    ):
                        raise LoadValidationError(
                            "record_key must be a SHA-256 hex digest"
                        )
                    file_sha256 = row["file_sha256"].strip()
                    if len(file_sha256) != 64 or any(
                        character not in "0123456789abcdef"
                        for character in file_sha256.lower()
                    ):
                        raise LoadValidationError(
                            "file_sha256 must be a SHA-256 hex digest"
                        )
                    source_url = validate_url(row["source_url"])
                    yield LoadRecord(
                        record_key=record_key.lower(),
                        source_schema=schema,
                        source_file=row["source_file"].strip(),
                        source_url=source_url,
                        data_snapshot=validate_timestamp(row["data_snapshot"]),
                        file_sha256=file_sha256.lower(),
                        payload_json=validate_payload(row["payload_json"]),
                        master_product_id=master_map.get((schema, source_url)),
                    )
                except (KeyError, LoadValidationError) as exc:
                    raise LoadValidationError(f"{path}:{line_number}: {exc}") from exc


def batched(records: Iterable[LoadRecord], size: int) -> Iterator[list[LoadRecord]]:
    batch: list[LoadRecord] = []
    for record in records:
        batch.append(record)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def resolve_dsn(target: str, explicit_dsn: str | None) -> str:
    if explicit_dsn:
        return explicit_dsn
    environment_names = {
        "supabase": ("SUPABASE_DB_URL", "DATABASE_URL"),
        "postgres": ("DATABASE_URL",),
        "aws": ("AWS_POSTGRES_URL", "DATABASE_URL"),
        "azure": ("AZURE_POSTGRES_URL", "DATABASE_URL"),
    }[target]
    for name in environment_names:
        value = os.environ.get(name)
        if value:
            return value
    expected = " or ".join(environment_names)
    raise RuntimeError(
        f"No database connection string was supplied; use --dsn or set {expected}"
    )


def query_for_schema(schema: str) -> str:
    # This function is the only place where an identifier enters SQL, and it
    # comes from the fixed allowlist above rather than CSV/user interpolation.
    function_name = SCHEMA_FUNCTIONS[schema]
    if schema == "original":
        return (
            "select source_serial_number, product_id, instance_number, "
            "operation, match_method, completeness_score "
            f"from {function_name}(%s::jsonb, %s, %s::timestamptz, %s)"
        )
    return (
        "select source_serial_number, product_id, instance_number, "
        "operation, match_method, completeness_score "
        f"from {function_name}(%s::jsonb, %s, %s::timestamptz, %s, %s)"
    )


def write_failures(path: Path, failures: Sequence[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FAILURE_FIELDS)
            writer.writeheader()
            writer.writerows(failures)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def import_psycopg() -> Any:
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Database loading requires psycopg 3; install requirements.txt"
        ) from exc
    return psycopg


def preflight_database(connection: Any, active_schemas: set[str]) -> None:
    with connection.cursor() as cursor:
        cursor.execute("show server_version_num")
        version_number = int(cursor.fetchone()[0])
        if version_number < 150000:
            raise RuntimeError(
                f"PostgreSQL 15 or newer is required; server reports {version_number}"
            )
        for schema in sorted(active_schemas, key=SCHEMA_ORDER.index):
            signature = (
                "jsonb,text,timestamp with time zone,text"
                if schema == "original"
                else "jsonb,text,timestamp with time zone,text,bigint"
            )
            procedure = f"{SCHEMA_FUNCTIONS[schema]}({signature})"
            cursor.execute("select to_regprocedure(%s)", (procedure,))
            if cursor.fetchone()[0] is None:
                raise RuntimeError(
                    f"Missing {procedure}; apply db/schema_v1.sql and "
                    "db/functions_v1.sql before loading"
                )
    connection.commit()


def start_run(
    connection: Any,
    target: str,
    csv_root: Path,
    active_schemas: set[str],
) -> int:
    details = json.dumps(
        {"schemas": sorted(active_schemas), "csv_root": str(csv_root)},
        separators=(",", ":"),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "select api.start_ingest_run(%s, %s, %s::jsonb)",
            (target, str(csv_root / "_manifest" / "manifest.json"), details),
        )
        run_id = int(cursor.fetchone()[0])
    connection.commit()
    return run_id


def finish_run(
    connection: Any,
    run_id: int,
    attempted: int,
    succeeded: int,
    failed: int,
    status: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "select api.finish_ingest_run(%s, %s, %s, %s, %s, %s::jsonb)",
            (run_id, attempted, succeeded, failed, status, "{}"),
        )
    connection.commit()


def log_database_reject(
    connection: Any,
    run_id: int,
    record: LoadRecord,
    error: Exception,
) -> None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select api.log_ingest_reject(%s, %s, %s, %s, %s, %s, %s::jsonb)",
                (
                    run_id,
                    record.source_schema,
                    record.source_file,
                    record.source_url,
                    type(error).__name__,
                    str(error),
                    record.payload_json,
                ),
            )
        connection.commit()
    except Exception as reject_error:
        connection.rollback()
        LOG.warning("Could not persist reject metadata: %s", reject_error)


def execute_batch(connection: Any, batch: Sequence[LoadRecord]) -> None:
    grouped: dict[str, list[LoadRecord]] = defaultdict(list)
    for record in batch:
        grouped[record.source_schema].append(record)
    with connection.transaction():
        with connection.cursor() as cursor:
            for schema in SCHEMA_ORDER:
                records = grouped.get(schema)
                if not records:
                    continue
                cursor.executemany(
                    query_for_schema(schema),
                    [record.parameters() for record in records],
                    returning=False,
                )


def execute_one(connection: Any, record: LoadRecord) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(query_for_schema(record.source_schema), record.parameters())
            result = cursor.fetchone()
            if result is None:
                raise RuntimeError("Ingestion function returned no result")


def dry_run(
    paths: Sequence[Path],
    master_map: Mapping[tuple[str, str], int],
    limit: int | None,
) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    mapped = 0
    total = 0
    seen: set[tuple[str, str, str]] = set()
    for record in iter_load_records(paths, master_map):
        identity = (record.source_schema, record.source_url, record.data_snapshot)
        if identity in seen:
            raise LoadValidationError(
                "Duplicate source_schema/source_url/data_snapshot in CSV input: "
                f"{identity}"
            )
        seen.add(identity)
        counts[record.source_schema] += 1
        mapped += record.master_product_id is not None
        total += 1
        if limit is not None and total >= limit:
            break
    return {
        "validated_records": total,
        "records_by_schema": dict(sorted(counts.items())),
        "explicit_master_mappings": mapped,
        "record_files": [str(path) for path in paths],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load MobileInfoAnalytics canonical CSV records into PostgreSQL."
    )
    parser.add_argument("--csv-root", type=Path, default=DEFAULT_CSV_ROOT)
    parser.add_argument(
        "--target",
        choices=("supabase", "postgres", "aws", "azure"),
        default="supabase",
        help=(
            "Select the DSN environment convention. AWS means RDS/Aurora "
            "PostgreSQL; Azure means Azure Database for PostgreSQL."
        ),
    )
    parser.add_argument(
        "--dsn",
        help="PostgreSQL connection string. Prefer the target-specific environment variable.",
    )
    parser.add_argument(
        "--schema",
        action="append",
        choices=SCHEMA_ORDER,
        default=[],
        help="Load only this source schema (repeatable).",
    )
    parser.add_argument(
        "--master-map",
        type=Path,
        help="Optional reviewed CSV: source_schema,source_url,product_id.",
    )
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--limit", type=int, help="Load at most this many records.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate all selected CSV rows without connecting to a database.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Abort on the first database row failure instead of quarantining it.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=15,
        help="Database connection timeout in seconds.",
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
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")

    try:
        selected = set(args.schema) if args.schema else None
        csv_root = args.csv_root.resolve()
        paths = discover_record_files(csv_root, selected)
        master_map = load_master_map(
            args.master_map.resolve() if args.master_map else None
        )
        validation = dry_run(paths, master_map, args.limit)
        if args.dry_run:
            print(json.dumps(validation, indent=2, ensure_ascii=False))
            return 0

        active_schemas = set(validation["records_by_schema"])
        if validation["validated_records"] == 0:
            raise LoadValidationError("The selected CSV files contain no data rows")
        dsn = resolve_dsn(args.target, args.dsn)
        psycopg = import_psycopg()
        failures: list[dict[str, str]] = []
        attempted = 0
        succeeded = 0
        failed = 0
        run_id: int | None = None
        fatal_error: Exception | None = None

        LOG.info(
            "Connecting to %s PostgreSQL; records=%d schemas=%s",
            args.target,
            validation["validated_records"],
            ",".join(sorted(active_schemas)),
        )
        with psycopg.connect(dsn, connect_timeout=args.connect_timeout) as connection:
            preflight_database(connection, active_schemas)
            run_id = start_run(connection, args.target, csv_root, active_schemas)
            source_records: Iterable[LoadRecord] = iter_load_records(paths, master_map)
            if args.limit is not None:
                source_records = islice(source_records, args.limit)

            try:
                for batch_number, batch in enumerate(
                    batched(source_records, args.batch_size), start=1
                ):
                    attempted += len(batch)
                    try:
                        execute_batch(connection, batch)
                        succeeded += len(batch)
                    except Exception as batch_error:
                        connection.rollback()
                        LOG.warning(
                            "Batch %d failed (%s); retrying each row to isolate rejects",
                            batch_number,
                            batch_error,
                        )
                        for record in batch:
                            try:
                                execute_one(connection, record)
                                succeeded += 1
                            except Exception as row_error:
                                connection.rollback()
                                failed += 1
                                failures.append(
                                    {
                                        "record_key": record.record_key,
                                        "source_schema": record.source_schema,
                                        "source_file": record.source_file,
                                        "source_url": record.source_url,
                                        "error_type": type(row_error).__name__,
                                        "error_message": str(row_error),
                                    }
                                )
                                LOG.error(
                                    "REJECT %s %s: %s",
                                    record.source_schema,
                                    record.source_url,
                                    row_error,
                                )
                                if run_id is not None:
                                    log_database_reject(
                                        connection, run_id, record, row_error
                                    )
                                if args.stop_on_error:
                                    raise
                    LOG.info(
                        "Batch %d complete: attempted=%d succeeded=%d failed=%d",
                        batch_number,
                        attempted,
                        succeeded,
                        failed,
                    )
            except Exception as exc:
                fatal_error = exc
            finally:
                status = (
                    "failed"
                    if fatal_error is not None
                    else "completed_with_errors"
                    if failed
                    else "completed"
                )
                if run_id is not None:
                    finish_run(
                        connection,
                        run_id,
                        attempted,
                        succeeded,
                        failed,
                        status,
                    )

        failure_path = csv_root / "_manifest" / "database_failures.csv"
        write_failures(failure_path, failures)
        if fatal_error is not None:
            raise fatal_error
        LOG.info(
            "Database load complete: run_id=%s attempted=%d succeeded=%d failed=%d",
            run_id,
            attempted,
            succeeded,
            failed,
        )
        return 0 if failed == 0 else 2
    except Exception as exc:
        LOG.error("Database load failed: %s", exc)
        if args.log_level == "DEBUG":
            LOG.exception("Detailed failure")
        return 1


if __name__ == "__main__":
    sys.exit(main())
