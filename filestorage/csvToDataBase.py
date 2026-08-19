#!/usr/bin/env python3
"""Upload jsonToCsv.py's Supabase-v3 CSV hierarchy into Supabase PostgreSQL.

This is a dependency-free, resumable loader for the CSV tree produced by
``filestorage/jsonToCsv.py``.  It uses Supabase's Data REST API directly and
requires only these environment variables (loaded from ``.env`` automatically):

    SUPABASE_URL="https://<project-ref>.supabase.co"
    SUPABASE_KEY="sb_secret_..."  # recommended, or legacy service_role JWT

Design goals
------------
* exact schema/header validation before writes
* foreign-key-safe table ordering
* deterministic/idempotent UPSERTs using the explicit BIGINT IDs in the CSVs
* bounded request size (row and byte limits)
* retry/backoff for transient HTTP/network failures
* resumable state saved after every committed REST batch
* batch bisection to identify a bad row instead of losing a whole table
* custom-schema exposure preflight before uploading anything
* post-load row-count verification
* no third-party Python packages

IMPORTANT
---------
The database schemas ``catalog``, ``specs``, ``listings``, ``metadata`` and
``staging`` must be added to Supabase Dashboard -> Data API -> Exposed schemas.
The supplied schema SQL already grants service_role access, but Data API schema
exposure is a Supabase project setting and cannot be inferred from GRANT alone.

The loader is safest against an empty freshly-created database.  On a brand-new
upload it refuses a non-empty target unless ``--allow-existing`` is explicitly
supplied.  Once a load has started, its state file makes interruption/restart
safe: just rerun the same command.
"""

from __future__ import annotations

import argparse
import base64
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


LOG = logging.getLogger("csvToDataBase")
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name.lower() == "filestorage" else Path.cwd()
DEFAULT_CSV_ROOT = PROJECT_ROOT / "filestorage" / "csvs"
ENV_URL = "SUPABASE_URL"
ENV_KEY = "SUPABASE_KEY"
STATE_VERSION = 1
STATE_FILENAME = "database_upload_state.json"
REPORT_FILENAME = "database_upload_report.json"
ERROR_FILENAME = "database_upload_errors.jsonl"
DEFAULT_BATCH_ROWS = 250
DEFAULT_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
DEFAULT_TIMEOUT_S = 120
DEFAULT_RETRIES = 6
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
EXPOSED_SCHEMAS = ("catalog", "specs", "listings", "metadata", "staging")

# Exact foreign-key-safe order emitted by jsonToCsv.py.
IMPORT_ORDER = [
    "metadata.scrape_runs",
    "catalog.companies",
    "catalog.products",
    "catalog.product_aliases",
    "specs.product_specs",
    "specs.spec_network",
    "specs.spec_body",
    "specs.spec_display",
    "specs.spec_platform",
    "specs.spec_memory",
    "specs.spec_camera_main",
    "specs.spec_camera_selfie",
    "specs.spec_connectivity",
    "specs.spec_battery",
    "listings.market_listings",
    "listings.listing_prices",
    "listings.listing_network",
    "listings.listing_body",
    "listings.listing_display",
    "listings.listing_platform",
    "listings.listing_memory",
    "listings.listing_camera_main",
    "listings.listing_camera_selfie",
    "listings.listing_connectivity",
    "listings.listing_battery",
    "metadata.data_quality",
    "metadata.etl_rejects",
    "staging.raw_json_records",
]

# Expected CSV columns, in database column order.
TABLE_FIELDS: dict[str, list[str]] = {
    "catalog.companies": ["company_id", "company_name", "company_slug", "created_at"],
    "catalog.products": ["product_id", "company_id", "mobile_name", "product_slug", "created_by_source", "created_at", "updated_at"],
    "catalog.product_aliases": ["alias_id", "product_id", "alias_name", "alias_slug", "source_domain", "created_at"],
    "specs.product_specs": ["product_id", "release_year", "release_month", "release_day", "announced_text", "status_text", "colors", "has_loudspeaker", "has_3_5mm_jack", "specs_source", "last_updated"],
    "specs.spec_network": ["product_id", "supports_2g", "supports_3g", "supports_4g", "supports_5g"],
    "specs.spec_body": ["product_id", "dim_length_mm", "dim_width_mm", "dim_depth_mm", "weight_grams", "build_materials", "has_normal_sim", "has_nano_sim", "has_esim", "ip_rating", "is_water_resistant", "is_dust_resistant"],
    "specs.spec_display": ["product_id", "screen_technology", "refresh_rate_hz", "peak_brightness_nits", "resolution_width", "resolution_height", "aspect_ratio", "pixel_density_ppi", "screen_protection"],
    "specs.spec_platform": ["product_id", "operating_system", "chipset_name", "chipset_node_nm", "cpu_description", "gpu_name"],
    "specs.spec_memory": ["product_id", "card_slot", "storage_ram_variants", "technology"],
    "specs.spec_camera_main": ["product_id", "sensor_specs", "photo_features", "video_modes"],
    "specs.spec_camera_selfie": ["product_id", "sensor_specs", "video_modes"],
    "specs.spec_connectivity": ["product_id", "wifi_standards", "bluetooth_version", "positioning_systems", "has_nfc", "has_infrared", "has_fm_radio", "has_usb_a", "has_usb_b", "has_micro_usb", "has_usb_c", "has_fp_rear", "has_fp_side", "has_fp_under_display"],
    "specs.spec_battery": ["product_id", "capacity_mah", "has_wireless_charging", "charging_specs"],
    "metadata.scrape_runs": ["run_id", "source_domain", "started_at", "finished_at", "records_processed", "records_succeeded", "records_failed", "run_status"],
    "metadata.etl_rejects": ["reject_id", "scrape_run_id", "source_domain", "source_url", "source_file", "reject_reason", "reject_detail", "raw_payload", "rejected_at", "resolved_at", "resolution_detail"],
    "metadata.data_quality": ["score_id", "product_id", "listing_id", "source_domain", "completeness_pct", "fields_populated", "fields_total", "scored_at"],
    "listings.market_listings": ["listing_id", "product_id", "instance_number", "source_domain", "source_url", "listing_title", "announced_text", "status_text", "release_year", "release_month", "release_day", "colors", "has_loudspeaker", "has_3_5mm_jack", "raw_payload", "scrape_run_id", "scraped_at"],
    "listings.listing_prices": ["price_entry_id", "listing_id", "currency_code", "amount", "price_index", "created_at"],
    "listings.listing_network": ["listing_id", "supports_2g", "supports_3g", "supports_4g", "supports_5g"],
    "listings.listing_body": ["listing_id", "dim_length_mm", "dim_width_mm", "dim_depth_mm", "weight_grams", "build_materials", "has_normal_sim", "has_nano_sim", "has_esim", "ip_rating", "is_water_resistant", "is_dust_resistant"],
    "listings.listing_display": ["listing_id", "screen_technology", "refresh_rate_hz", "peak_brightness_nits", "resolution_width", "resolution_height", "aspect_ratio", "pixel_density_ppi", "screen_protection"],
    "listings.listing_platform": ["listing_id", "operating_system", "chipset_name", "chipset_node_nm", "cpu_description", "gpu_name"],
    "listings.listing_memory": ["listing_id", "card_slot", "storage_ram_variants", "technology"],
    "listings.listing_camera_main": ["listing_id", "sensor_specs", "photo_features", "video_modes"],
    "listings.listing_camera_selfie": ["listing_id", "sensor_specs", "video_modes"],
    "listings.listing_connectivity": ["listing_id", "wifi_standards", "bluetooth_version", "positioning_systems", "has_nfc", "has_infrared", "has_fm_radio", "has_usb_a", "has_usb_b", "has_micro_usb", "has_usb_c", "has_fp_rear", "has_fp_side", "has_fp_under_display"],
    "listings.listing_battery": ["listing_id", "capacity_mah", "has_wireless_charging", "charging_specs"],
    "staging.raw_json_records": ["staging_id", "record_key", "source_domain", "source_file", "source_url", "payload", "ingested_at", "processed_at", "status"],
}

PRIMARY_KEYS = {
    "catalog.companies": "company_id",
    "catalog.products": "product_id",
    "catalog.product_aliases": "alias_id",
    "specs.product_specs": "product_id",
    "specs.spec_network": "product_id",
    "specs.spec_body": "product_id",
    "specs.spec_display": "product_id",
    "specs.spec_platform": "product_id",
    "specs.spec_memory": "product_id",
    "specs.spec_camera_main": "product_id",
    "specs.spec_camera_selfie": "product_id",
    "specs.spec_connectivity": "product_id",
    "specs.spec_battery": "product_id",
    "metadata.scrape_runs": "run_id",
    "metadata.etl_rejects": "reject_id",
    "metadata.data_quality": "score_id",
    "listings.market_listings": "listing_id",
    "listings.listing_prices": "price_entry_id",
    "listings.listing_network": "listing_id",
    "listings.listing_body": "listing_id",
    "listings.listing_display": "listing_id",
    "listings.listing_platform": "listing_id",
    "listings.listing_memory": "listing_id",
    "listings.listing_camera_main": "listing_id",
    "listings.listing_camera_selfie": "listing_id",
    "listings.listing_connectivity": "listing_id",
    "listings.listing_battery": "listing_id",
    "staging.raw_json_records": "staging_id",
}

BIGINT_COLUMNS = {
    "company_id", "product_id", "alias_id", "run_id", "scrape_run_id", "score_id",
    "listing_id", "price_entry_id", "staging_id", "reject_id",
}
INT_COLUMNS = {
    "release_year", "release_day", "refresh_rate_hz", "peak_brightness_nits",
    "resolution_width", "resolution_height", "pixel_density_ppi", "chipset_node_nm",
    "capacity_mah", "records_processed", "records_succeeded", "records_failed",
    "instance_number", "price_index", "fields_populated", "fields_total",
}
NUMERIC_COLUMNS = {
    "dim_length_mm", "dim_width_mm", "dim_depth_mm", "weight_grams", "amount",
    "completeness_pct",
}
BOOLEAN_COLUMNS = {
    "has_loudspeaker", "has_3_5mm_jack", "supports_2g", "supports_3g", "supports_4g",
    "supports_5g", "has_normal_sim", "has_nano_sim", "has_esim", "is_water_resistant",
    "is_dust_resistant", "has_nfc", "has_infrared", "has_fm_radio", "has_usb_a",
    "has_usb_b", "has_micro_usb", "has_usb_c", "has_fp_rear", "has_fp_side",
    "has_fp_under_display", "has_wireless_charging",
}
ARRAY_COLUMNS = {"colors", "sensor_specs", "video_modes", "charging_specs"}
JSON_COLUMNS = {"storage_ram_variants", "raw_payload", "payload"}

UNIQUE_KEYS: dict[str, list[tuple[str, ...]]] = {
    "catalog.companies": [("company_id",), ("company_slug",)],
    "catalog.products": [("product_id",), ("product_slug",)],
    "catalog.product_aliases": [("alias_id",), ("alias_slug",)],
    "specs.product_specs": [("product_id",)],
    "metadata.scrape_runs": [("run_id",)],
    "metadata.etl_rejects": [("reject_id",)],
    "metadata.data_quality": [("score_id",)],
    "listings.market_listings": [("listing_id",), ("source_url",), ("product_id", "source_domain", "instance_number")],
    "listings.listing_prices": [("price_entry_id",), ("listing_id", "currency_code", "price_index")],
    "staging.raw_json_records": [("staging_id",)],
}
for _table in IMPORT_ORDER:
    if _table.startswith("specs.spec_"):
        UNIQUE_KEYS.setdefault(_table, [("product_id",)])
    if _table.startswith("listings.listing_") and _table != "listings.listing_prices":
        UNIQUE_KEYS.setdefault(_table, [("listing_id",)])

FK_SPECS: dict[str, list[tuple[str, str, bool]]] = {
    "catalog.products": [("company_id", "catalog.companies", False)],
    "catalog.product_aliases": [("product_id", "catalog.products", False)],
    "specs.product_specs": [("product_id", "catalog.products", False)],
    "listings.market_listings": [
        ("product_id", "catalog.products", False),
        ("scrape_run_id", "metadata.scrape_runs", True),
    ],
    "listings.listing_prices": [("listing_id", "listings.market_listings", False)],
    "metadata.data_quality": [
        ("product_id", "catalog.products", True),
        # listing_id is not declared as an FK in schema_supabase.sql, but jsonToCsv
        # uses it as a semantic relationship; validate it when populated.
        ("listing_id", "listings.market_listings", True),
    ],
    "metadata.etl_rejects": [("scrape_run_id", "metadata.scrape_runs", True)],
}
for _table in IMPORT_ORDER:
    if _table.startswith("specs.spec_"):
        FK_SPECS.setdefault(_table, [("product_id", "specs.product_specs", False)])
    if _table.startswith("listings.listing_") and _table != "listings.listing_prices":
        FK_SPECS.setdefault(_table, [("listing_id", "listings.market_listings", False)])

# Required non-null columns which must never be blank in the generated CSV.
NOT_NULL_COLUMNS: dict[str, set[str]] = {
    "catalog.companies": {"company_id", "company_name", "company_slug", "created_at"},
    "catalog.products": {"product_id", "company_id", "mobile_name", "product_slug", "created_by_source", "created_at", "updated_at"},
    "catalog.product_aliases": {"alias_id", "product_id", "alias_name", "alias_slug", "created_at"},
    "specs.product_specs": {"product_id", "release_year", "release_month", "has_loudspeaker", "has_3_5mm_jack", "specs_source", "last_updated"},
    "metadata.scrape_runs": {"run_id", "source_domain", "started_at", "records_processed", "records_succeeded", "records_failed", "run_status"},
    "metadata.etl_rejects": {"reject_id", "source_domain", "reject_reason", "rejected_at"},
    "metadata.data_quality": {"score_id", "source_domain", "completeness_pct", "fields_populated", "fields_total", "scored_at"},
    "listings.market_listings": {"listing_id", "product_id", "instance_number", "source_domain", "source_url", "listing_title", "release_year", "release_month", "has_loudspeaker", "has_3_5mm_jack", "scraped_at"},
    "listings.listing_prices": {"price_entry_id", "listing_id", "currency_code", "amount", "price_index", "created_at"},
    "staging.raw_json_records": {"staging_id", "source_domain", "source_file", "payload", "ingested_at", "status"},
}
# All one-to-one spec/listing tables have a non-null PK and most flag/numeric
# values are guaranteed by jsonToCsv.  Their blank nullable text columns remain OK.
for _t in IMPORT_ORDER:
    if _t.startswith("specs.spec_"):
        NOT_NULL_COLUMNS.setdefault(_t, {"product_id"})
    if _t.startswith("listings.listing_") and _t != "listings.listing_prices":
        NOT_NULL_COLUMNS.setdefault(_t, {"listing_id"})


class UploadError(RuntimeError):
    pass


class CsvContractError(ValueError):
    pass


class SupabaseHTTPError(UploadError):
    def __init__(self, status: int, reason: str, body: str, headers: Mapping[str, str] | None = None):
        self.status = status
        self.reason = reason
        self.body = body
        self.headers = dict(headers or {})
        message = f"HTTP {status} {reason}: {body[:1200]}"
        super().__init__(message)


@dataclass(frozen=True)
class CsvFileInfo:
    table: str
    path: Path
    rows: int
    sha256: str


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


# -----------------------------------------------------------------------------
# Environment / config
# -----------------------------------------------------------------------------

def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_dotenv() -> Path | None:
    """Tiny .env loader; existing process environment always wins."""
    candidates = []
    for path in (
        Path.cwd() / ".env",
        SCRIPT_DIR / ".env",
        SCRIPT_DIR.parent / ".env",
        PROJECT_ROOT / ".env",
    ):
        if path not in candidates:
            candidates.append(path)
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            os.environ.setdefault(key, _strip_env_value(value))
        return path
    return None


def _jwt_role(token: str) -> str | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        obj = json.loads(base64.urlsafe_b64decode(payload.encode()).decode("utf-8"))
        role = obj.get("role")
        return str(role) if role is not None else None
    except Exception:
        return None


def validate_write_key(key: str) -> str:
    """Return key mode: modern_secret or legacy_service_role."""
    if key.startswith("sb_secret_"):
        return "modern_secret"
    if key.startswith("sb_publishable_"):
        raise UploadError(
            "SUPABASE_KEY is a publishable key. This ETL needs a backend secret key "
            "(sb_secret_...) or legacy service_role key because the supplied RLS policies "
            "allow writes only to service_role."
        )
    role = _jwt_role(key)
    if role == "service_role":
        return "legacy_service_role"
    if role in {"anon", "authenticated"}:
        raise UploadError(
            f"SUPABASE_KEY is a {role!r} JWT, not a service_role write key."
        )
    raise UploadError(
        "SUPABASE_KEY format was not recognized as sb_secret_... or a legacy "
        "service_role JWT. Refusing to upload with an unverified write credential."
    )


def normalize_supabase_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if not re.fullmatch(r"https://[^/]+", url, flags=re.IGNORECASE):
        raise UploadError("SUPABASE_URL must look like https://<project-ref>.supabase.co")
    return url


def load_supabase_settings() -> tuple[str, str, str, Path | None]:
    env_path = load_dotenv()
    url = os.environ.get(ENV_URL, "").strip()
    key = os.environ.get(ENV_KEY, "").strip()
    missing = [name for name, value in ((ENV_URL, url), (ENV_KEY, key)) if not value]
    if missing:
        raise UploadError("Missing environment variable(s): " + ", ".join(missing))
    url = normalize_supabase_url(url)
    mode = validate_write_key(key)
    return url, key, mode, env_path


# -----------------------------------------------------------------------------
# CSV parsing / validation
# -----------------------------------------------------------------------------

def csv_path(csv_root: Path, table: str) -> Path:
    schema, name = table.split(".", 1)
    return csv_root / schema / f"{name}.csv"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _parse_pg_text_array(value: str, *, field: str) -> list[str]:
    value = value.strip()
    if value == "{}":
        return []
    if not (value.startswith("{") and value.endswith("}")):
        raise CsvContractError(f"{field}: invalid PostgreSQL TEXT[] literal {value!r}")
    inner = value[1:-1]
    if not inner:
        return []
    try:
        reader = csv.reader([inner], delimiter=",", quotechar='"', escapechar="\\", strict=True)
        result = next(reader)
    except csv.Error as exc:
        raise CsvContractError(f"{field}: invalid PostgreSQL TEXT[] literal: {exc}") from exc
    return [item for item in result if item != "NULL"]


def _parse_bool(value: str, *, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    raise CsvContractError(f"{field}: expected boolean, got {value!r}")


def _parse_int(value: str, *, field: str) -> int:
    try:
        # Disallow accidental floating-point IDs / integers.
        if not re.fullmatch(r"[-+]?\d+", value.strip()):
            raise ValueError
        return int(value)
    except ValueError as exc:
        raise CsvContractError(f"{field}: expected integer, got {value!r}") from exc


def _parse_number(value: str, *, field: str) -> int | float:
    try:
        number = Decimal(value.strip())
    except InvalidOperation as exc:
        raise CsvContractError(f"{field}: expected numeric value, got {value!r}") from exc
    if not number.is_finite():
        raise CsvContractError(f"{field}: numeric value must be finite")
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def parse_csv_value(column: str, value: str) -> Any:
    if value == "":
        return None
    if column in BOOLEAN_COLUMNS:
        return _parse_bool(value, field=column)
    if column in BIGINT_COLUMNS or column in INT_COLUMNS:
        return _parse_int(value, field=column)
    if column in NUMERIC_COLUMNS:
        return _parse_number(value, field=column)
    if column in JSON_COLUMNS:
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise CsvContractError(f"{column}: invalid JSON: {exc}") from exc
    if column in ARRAY_COLUMNS:
        return _parse_pg_text_array(value, field=column)
    return value


def validate_row(table: str, raw: Mapping[str, str], line_number: int, path: Path) -> dict[str, Any]:
    expected = TABLE_FIELDS[table]
    missing_required = [
        col for col in NOT_NULL_COLUMNS.get(table, set())
        if raw.get(col, "") == ""
    ]
    if missing_required:
        raise CsvContractError(
            f"{path}:{line_number}: blank NOT NULL field(s): {sorted(missing_required)}"
        )
    parsed: dict[str, Any] = {}
    try:
        for column in expected:
            parsed[column] = parse_csv_value(column, raw.get(column, ""))
    except CsvContractError as exc:
        raise CsvContractError(f"{path}:{line_number}: {exc}") from exc

    # Extra high-value constraints that catch converter/database mismatches early.
    if "currency_code" in parsed and parsed["currency_code"] is not None:
        code = str(parsed["currency_code"]).upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise CsvContractError(f"{path}:{line_number}: currency_code must be 3 uppercase letters")
        parsed["currency_code"] = code
    if "release_month" in parsed and parsed["release_month"] is not None:
        if parsed["release_month"] not in {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"}:
            raise CsvContractError(f"{path}:{line_number}: invalid release_month {parsed['release_month']!r}")
    if "source_url" in parsed and parsed["source_url"] is not None:
        if not str(parsed["source_url"]).startswith(("http://", "https://")):
            raise CsvContractError(f"{path}:{line_number}: invalid source_url")
    return parsed


def iter_table_rows(info: CsvFileInfo, *, skip: int = 0) -> Iterator[dict[str, Any]]:
    expected = TABLE_FIELDS[info.table]
    with info.path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual = list(reader.fieldnames or [])
        if actual != expected:
            raise CsvContractError(
                f"{info.path}: CSV header does not match schema.\n"
                f"expected={expected}\nactual={actual}"
            )
        for index, raw in enumerate(reader):
            if index < skip:
                continue
            yield validate_row(info.table, raw, index + 2, info.path)


def inspect_csv_tree(csv_root: Path) -> dict[str, CsvFileInfo]:
    if not csv_root.is_dir():
        raise FileNotFoundError(f"CSV root does not exist: {csv_root}")
    manifest_path = csv_root / "_manifest" / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CsvContractError(f"Invalid CSV manifest {manifest_path}: {exc}") from exc
        if manifest.get("format_version") != 3:
            raise CsvContractError(
                f"Expected jsonToCsv format_version=3, found {manifest.get('format_version')!r}"
            )

    infos: dict[str, CsvFileInfo] = {}
    manifest_counts = manifest.get("rows_by_table") if isinstance(manifest.get("rows_by_table"), dict) else {}
    for table in IMPORT_ORDER:
        path = csv_path(csv_root, table)
        if not path.is_file():
            raise CsvContractError(f"Missing required CSV: {path}")
        expected = TABLE_FIELDS[table]
        count = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration:
                raise CsvContractError(f"Empty CSV file: {path}")
            if header != expected:
                raise CsvContractError(
                    f"{path}: header mismatch.\nexpected={expected}\nactual={header}"
                )
            for count, _ in enumerate(reader, start=1):
                pass
        if table in manifest_counts and int(manifest_counts[table]) != count:
            raise CsvContractError(
                f"{path}: manifest says {manifest_counts[table]} rows but CSV has {count}"
            )
        infos[table] = CsvFileInfo(table, path, count, sha256_file(path))
    return infos


def validate_all_rows(infos: Mapping[str, CsvFileInfo]) -> None:
    """Typed validation plus local UNIQUE/FK integrity before any network write."""
    total = 0
    primary_values: dict[str, set[Any]] = {}
    for table in IMPORT_ORDER:
        info = infos[table]
        uniqueness = {columns: set() for columns in UNIQUE_KEYS.get(table, [(PRIMARY_KEYS[table],)])}
        pk_values: set[Any] = set()
        for row in iter_table_rows(info):
            total += 1
            # Positive explicit identity/FK values are part of jsonToCsv's contract.
            for column in BIGINT_COLUMNS:
                if column in row and row[column] is not None and int(row[column]) <= 0:
                    raise CsvContractError(f"{info.path}: {column} must be a positive BIGINT")

            for columns, seen in uniqueness.items():
                key = tuple(row.get(column) for column in columns)
                # PostgreSQL UNIQUE permits multiple NULLs; generated unique keys here
                # are expected non-null, but preserve correct NULL semantics generally.
                if any(value is None for value in key):
                    continue
                if key in seen:
                    raise CsvContractError(f"{info.path}: duplicate unique key {columns}={key}")
                seen.add(key)

            for column, parent_table, nullable in FK_SPECS.get(table, []):
                value = row.get(column)
                if value is None and nullable:
                    continue
                if value is None:
                    raise CsvContractError(f"{info.path}: required FK {column} is null")
                parent_keys = primary_values.get(parent_table, set())
                if value not in parent_keys:
                    raise CsvContractError(
                        f"{info.path}: FK {column}={value!r} has no parent in {parent_table}"
                    )

            pk_values.add(row[PRIMARY_KEYS[table]])
        primary_values[table] = pk_values
        LOG.info("Validated %-38s %7d row(s)", table, info.rows)
    LOG.info(
        "Local CSV validation complete: %d relational rows across %d tables; UNIQUE/FK checks passed",
        total, len(IMPORT_ORDER),
    )


# -----------------------------------------------------------------------------
# Supabase REST client
# -----------------------------------------------------------------------------

class SupabaseRestClient:
    def __init__(self, base_url: str, key: str, key_mode: str, *, timeout: int, retries: int):
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.key_mode = key_mode
        self.timeout = timeout
        self.retries = retries

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "apikey": self.key,
            "User-Agent": "MobileInfoAnalytics-ETL/3",
        }
        # Modern sb_secret_ keys authenticate through `apikey` and are not JWTs.
        # Legacy service_role keys are JWTs and should also be supplied as Bearer.
        if self.key_mode == "legacy_service_role":
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        schema: str,
        query: Mapping[str, str] | None = None,
        body: bytes | None = None,
        extra_headers: Mapping[str, str] | None = None,
        retry: bool = True,
    ) -> HttpResponse:
        url = self.base_url + "/rest/v1/" + path.lstrip("/")
        if query:
            url += "?" + urlencode(query, safe=",")
        headers = self._auth_headers()
        headers["Accept"] = "application/json"
        headers["Accept-Profile"] = schema
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Profile"] = schema
        if extra_headers:
            headers.update(extra_headers)

        max_attempts = self.retries if retry else 1
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            req = Request(url, data=body, method=method, headers=headers)
            try:
                with urlopen(req, timeout=self.timeout) as response:
                    data = response.read()
                    return HttpResponse(
                        int(response.status),
                        {str(k): str(v) for k, v in response.headers.items()},
                        data,
                    )
            except HTTPError as exc:
                payload = exc.read().decode("utf-8", errors="replace")
                err = SupabaseHTTPError(exc.code, str(exc.reason), payload, dict(exc.headers.items()))
                last_exc = err
                if exc.code not in RETRYABLE_HTTP or attempt >= max_attempts:
                    raise err
                retry_after = exc.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = min(float(retry_after), 60.0)
                else:
                    delay = min(2 ** (attempt - 1), 30) + random.uniform(0.0, 0.75)
                LOG.warning("Transient Supabase HTTP %s; retry %d/%d in %.1fs", exc.code, attempt, max_attempts, delay)
                time.sleep(delay)
            except (URLError, TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt >= max_attempts:
                    raise UploadError(f"Network request failed after {max_attempts} attempts: {exc}") from exc
                delay = min(2 ** (attempt - 1), 30) + random.uniform(0.0, 0.75)
                LOG.warning("Supabase network error: %s; retry %d/%d in %.1fs", exc, attempt, max_attempts, delay)
                time.sleep(delay)
        raise UploadError(f"Request failed: {last_exc}")

    def count_rows(self, table: str) -> int:
        schema, name = table.split(".", 1)
        pk = PRIMARY_KEYS[table]
        response = self.request(
            "GET",
            name,
            schema=schema,
            query={"select": pk, "limit": "1"},
            extra_headers={"Prefer": "count=exact", "Range": "0-0"},
        )
        content_range = response.headers.get("Content-Range") or response.headers.get("content-range")
        if not content_range or "/" not in content_range:
            raise UploadError(f"Supabase did not return Content-Range for {table}")
        total = content_range.rsplit("/", 1)[1]
        if total == "*":
            raise UploadError(f"Supabase did not provide an exact row count for {table}")
        return int(total)

    def upsert_rows(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        schema, name = table.split(".", 1)
        pk = PRIMARY_KEYS[table]
        body = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.request(
            "POST",
            name,
            schema=schema,
            query={"on_conflict": pk},
            body=body,
            extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )


def explain_schema_exposure(exc: SupabaseHTTPError, schema: str) -> UploadError:
    body = exc.body.lower()
    if "schema" in body and ("exposed" in body or "db-schemas" in body or "must be one of" in body or "not found" in body):
        return UploadError(
            f"Supabase Data API cannot access custom schema {schema!r}. In the Supabase Dashboard, "
            "open Data API/API settings and add these schemas to Exposed schemas: "
            + ", ".join(EXPOSED_SCHEMAS)
            + ". The attached SQL grants permissions, but custom-schema API exposure is a project setting. "
            f"Original response: {exc}"
        )
    return exc


def preflight(client: SupabaseRestClient) -> dict[str, int]:
    probes = {
        "catalog": "catalog.companies",
        "specs": "specs.product_specs",
        "listings": "listings.market_listings",
        "metadata": "metadata.scrape_runs",
        "staging": "staging.raw_json_records",
    }
    counts: dict[str, int] = {}
    for schema, table in probes.items():
        try:
            counts[table] = client.count_rows(table)
        except SupabaseHTTPError as exc:
            raise explain_schema_exposure(exc, schema) from exc
    return counts


# -----------------------------------------------------------------------------
# Resumable upload
# -----------------------------------------------------------------------------

def state_path_for(csv_root: Path) -> Path:
    path = csv_root / "_manifest" / STATE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def report_path_for(csv_root: Path) -> Path:
    path = csv_root / "_manifest" / REPORT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def error_path_for(csv_root: Path) -> Path:
    path = csv_root / "_manifest" / ERROR_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def atomic_json(path: Path, obj: Any) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def csv_contract_fingerprint(infos: Mapping[str, CsvFileInfo]) -> str:
    digest = hashlib.sha256()
    for table in IMPORT_ORDER:
        info = infos[table]
        digest.update(table.encode())
        digest.update(b"\0")
        digest.update(str(info.rows).encode())
        digest.update(b"\0")
        digest.update(info.sha256.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise UploadError(f"Upload state is corrupt: {path}: {exc}") from exc
    if not isinstance(obj, dict) or obj.get("version") != STATE_VERSION:
        raise UploadError(f"Unsupported upload state format in {path}; use --reset-state")
    return obj


def new_state(base_url: str, contract_fp: str, infos: Mapping[str, CsvFileInfo]) -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "project_url": base_url,
        "contract_fingerprint": contract_fp,
        "tables": {
            table: {
                "file_sha256": infos[table].sha256,
                "expected_rows": infos[table].rows,
                "uploaded_rows": 0,
                "complete": infos[table].rows == 0,
            }
            for table in IMPORT_ORDER
        },
        "complete": False,
        "created_at_epoch": time.time(),
        "updated_at_epoch": time.time(),
    }


def ensure_state_compatible(state: dict[str, Any], base_url: str, contract_fp: str) -> None:
    if state.get("project_url") != base_url:
        raise UploadError(
            "Existing upload state belongs to a different Supabase project. Use --reset-state only "
            "if you intentionally want to start this CSV load against the current project."
        )
    if state.get("contract_fingerprint") != contract_fp:
        raise UploadError(
            "CSV files changed since this upload state was created. Refusing to mix two datasets. "
            "Use --reset-state after confirming the target database is suitable for a replay."
        )


def _row_identity(table: str, row: Mapping[str, Any]) -> str:
    pk = PRIMARY_KEYS[table]
    return f"{pk}={row.get(pk)!r}"


def append_error(path: Path, table: str, row: Mapping[str, Any], exc: Exception) -> None:
    record = {
        "table": table,
        "row_identity": _row_identity(table, row),
        "error": str(exc),
        "time_epoch": time.time(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def encoded_size(row: Mapping[str, Any]) -> int:
    return len(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")) + 1


def iter_batches(rows: Iterable[dict[str, Any]], max_rows: int, max_bytes: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    size = 2
    for row in rows:
        row_size = encoded_size(row)
        if row_size + 2 > max_bytes:
            # A single huge row is allowed through; server response will decide.
            if batch:
                yield batch
                batch = []
                size = 2
            yield [row]
            continue
        if batch and (len(batch) >= max_rows or size + row_size > max_bytes):
            yield batch
            batch = []
            size = 2
        batch.append(row)
        size += row_size
    if batch:
        yield batch


def send_batch_resilient(
    client: SupabaseRestClient,
    table: str,
    rows: list[dict[str, Any]],
    error_path: Path,
    *,
    continue_on_error: bool,
) -> tuple[int, int]:
    """Return (succeeded_rows, failed_rows).  Recursively isolates deterministic bad rows."""
    if not rows:
        return 0, 0
    try:
        client.upsert_rows(table, rows)
        return len(rows), 0
    except SupabaseHTTPError as exc:
        # 413 is definitely size-related.  400/409/422 can be row-specific; bisect
        # to isolate it, while auth/schema/server issues were handled/retried earlier.
        splittable = exc.status in {400, 409, 413, 422}
        if len(rows) > 1 and splittable:
            middle = len(rows) // 2
            LOG.warning("%s batch of %d rejected (HTTP %d); isolating by bisection", table, len(rows), exc.status)
            left = send_batch_resilient(client, table, rows[:middle], error_path, continue_on_error=continue_on_error)
            right = send_batch_resilient(client, table, rows[middle:], error_path, continue_on_error=continue_on_error)
            return left[0] + right[0], left[1] + right[1]
        if len(rows) == 1:
            append_error(error_path, table, rows[0], exc)
            if continue_on_error:
                LOG.error("Skipping failed %s row %s: %s", table, _row_identity(table, rows[0]), exc)
                return 0, 1
            raise UploadError(
                f"Database rejected {table} row {_row_identity(table, rows[0])}. "
                f"Details were written to {error_path}. Error: {exc}"
            ) from exc
        raise


def upload_table(
    client: SupabaseRestClient,
    info: CsvFileInfo,
    state: dict[str, Any],
    state_path: Path,
    error_path: Path,
    *,
    batch_rows: int,
    max_payload_bytes: int,
    continue_on_error: bool,
) -> tuple[int, int]:
    table_state = state["tables"][info.table]
    if table_state.get("complete"):
        LOG.info("Skip complete %-38s %7d row(s)", info.table, info.rows)
        return int(table_state.get("uploaded_rows", 0)), 0
    offset = int(table_state.get("uploaded_rows", 0))
    if offset > info.rows:
        raise UploadError(f"State offset {offset} exceeds {info.table} CSV row count {info.rows}")
    uploaded_this_call = 0
    failed_this_call = 0
    rows_iter = iter_table_rows(info, skip=offset)
    for batch in iter_batches(rows_iter, batch_rows, max_payload_bytes):
        succeeded, failed = send_batch_resilient(
            client, info.table, batch, error_path, continue_on_error=continue_on_error
        )
        # Resume offsets are safe only when every input row in the batch was either
        # committed or deliberately skipped with --continue-on-error.
        consumed = len(batch)
        offset += consumed
        uploaded_this_call += succeeded
        failed_this_call += failed
        table_state["uploaded_rows"] = offset
        table_state["failed_rows"] = int(table_state.get("failed_rows", 0)) + failed
        table_state["complete"] = offset >= info.rows
        state["updated_at_epoch"] = time.time()
        atomic_json(state_path, state)
        LOG.info("Uploaded %-38s %7d/%-7d", info.table, offset, info.rows)
    if info.rows == 0:
        table_state["complete"] = True
        state["updated_at_epoch"] = time.time()
        atomic_json(state_path, state)
    return uploaded_this_call, failed_this_call


def verify_database_counts(
    client: SupabaseRestClient,
    infos: Mapping[str, CsvFileInfo],
    *,
    exact: bool,
    state: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, int | bool]]:
    results: dict[str, dict[str, int | bool]] = {}
    for table in IMPORT_ORDER:
        failed = 0
        if state is not None:
            failed = int(state.get("tables", {}).get(table, {}).get("failed_rows", 0))
        expected = max(0, infos[table].rows - failed)
        actual = client.count_rows(table)
        ok = actual == expected if exact else actual >= expected
        results[table] = {
            "csv_rows": infos[table].rows,
            "failed_rows": failed,
            "expected_database_rows": expected,
            "actual": actual,
            "ok": ok,
        }
        if not ok:
            relation = "equal" if exact else "at least"
            raise UploadError(
                f"Verification failed for {table}: database has {actual}, expected {relation} {expected}"
            )
        LOG.info("Verified %-38s expected=%d actual=%d", table, expected, actual)
    return results


def run_upload(args: argparse.Namespace) -> dict[str, Any]:
    csv_root = args.csv_root.resolve()
    infos = inspect_csv_tree(csv_root)
    if not args.skip_local_validation:
        validate_all_rows(infos)
    total_rows = sum(info.rows for info in infos.values())
    summary = {
        "csv_root": str(csv_root),
        "tables": len(infos),
        "relational_rows": total_rows,
        "rows_by_table": {table: infos[table].rows for table in IMPORT_ORDER},
    }
    if args.dry_run:
        return {**summary, "mode": "dry_run", "network_used": False}

    base_url, key, key_mode, env_path = load_supabase_settings()
    LOG.info("Supabase project: %s", base_url)
    LOG.info("Credential mode: %s; .env=%s", key_mode, env_path or "process environment")
    client = SupabaseRestClient(base_url, key, key_mode, timeout=args.timeout, retries=args.retries)
    probe_counts = preflight(client)
    LOG.info("Supabase custom-schema preflight passed")

    state_path = state_path_for(csv_root)
    if args.reset_state and state_path.exists():
        state_path.unlink()
    state = load_state(state_path)
    contract_fp = csv_contract_fingerprint(infos)
    resumed = state is not None
    if state is None:
        # Strong first-run protection against mixing deterministic CSV IDs with an
        # unrelated pre-existing database.  Probe key tables before any write.
        nonempty = {table: count for table, count in probe_counts.items() if count > 0}
        if nonempty and not args.allow_existing:
            details = ", ".join(f"{table}={count}" for table, count in nonempty.items())
            raise UploadError(
                "Target database is not empty on first load (" + details + "). "
                "For the safest import use an empty database. If these existing rows are intentional "
                "and use compatible IDs, rerun with --allow-existing."
            )
        state = new_state(base_url, contract_fp, infos)
        atomic_json(state_path, state)
    else:
        ensure_state_compatible(state, base_url, contract_fp)
        if state.get("complete") and not args.replay_complete:
            LOG.info("Upload state already says complete; performing verification only")
            exact = not bool(state.get("allow_existing"))
            verification = verify_database_counts(client, infos, exact=exact, state=state) if not args.no_verify else {}
            return {**summary, "mode": "already_complete", "resumed": True, "verification": verification}
        if state.get("complete") and args.replay_complete:
            LOG.warning("Replaying a previously complete upload using idempotent primary-key upserts")
            for table in IMPORT_ORDER:
                state["tables"][table]["uploaded_rows"] = 0
                state["tables"][table]["failed_rows"] = 0
                state["tables"][table]["complete"] = infos[table].rows == 0
            state["complete"] = False
            state["updated_at_epoch"] = time.time()
            atomic_json(state_path, state)

    state["allow_existing"] = bool(args.allow_existing or state.get("allow_existing"))
    state["updated_at_epoch"] = time.time()
    atomic_json(state_path, state)

    if args.preflight_only:
        return {
            **summary,
            "mode": "preflight_only",
            "project_url": base_url,
            "key_mode": key_mode,
            "probe_counts": probe_counts,
            "resumable_state": str(state_path),
        }

    error_path = error_path_for(csv_root)
    if args.reset_state and error_path.exists():
        error_path.unlink()

    started = time.time()
    uploaded_rows = 0
    failed_rows = 0
    try:
        for table in IMPORT_ORDER:
            succeeded, failed = upload_table(
                client,
                infos[table],
                state,
                state_path,
                error_path,
                batch_rows=args.batch_rows,
                max_payload_bytes=args.max_payload_bytes,
                continue_on_error=args.continue_on_error,
            )
            uploaded_rows += succeeded
            failed_rows += failed
    except KeyboardInterrupt:
        state["updated_at_epoch"] = time.time()
        atomic_json(state_path, state)
        raise

    state["complete"] = all(bool(state["tables"][t].get("complete")) for t in IMPORT_ORDER)
    state["updated_at_epoch"] = time.time()
    atomic_json(state_path, state)
    if not state["complete"]:
        raise UploadError("Upload ended but one or more table states are incomplete")

    verification: dict[str, Any] = {}
    if not args.no_verify:
        exact = not bool(state.get("allow_existing")) and failed_rows == 0
        verification = verify_database_counts(client, infos, exact=exact, state=state)

    report = {
        **summary,
        "mode": "uploaded",
        "project_url": base_url,
        "key_mode": key_mode,
        "resumed": resumed,
        "uploaded_rows_this_run": uploaded_rows,
        "failed_rows_this_run": failed_rows,
        "elapsed_seconds": round(time.time() - started, 3),
        "verification": verification,
        "state_file": str(state_path),
        "error_file": str(error_path) if error_path.exists() else None,
    }
    atomic_json(report_path_for(csv_root), report)
    return report


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and resumably upload Supabase-v3 CSVs into Supabase."
    )
    parser.add_argument("--csv-root", type=Path, default=DEFAULT_CSV_ROOT)
    parser.add_argument("--batch-rows", type=int, default=DEFAULT_BATCH_ROWS)
    parser.add_argument("--max-payload-bytes", type=int, default=DEFAULT_MAX_PAYLOAD_BYTES)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--dry-run", action="store_true", help="Validate CSVs only; do not read credentials or use network.")
    parser.add_argument("--preflight-only", action="store_true", help="Validate CSVs, credentials, custom schemas and target counts; do not upload rows.")
    parser.add_argument("--allow-existing", action="store_true", help="Allow first upload into a database that already contains rows. Use only when intentional.")
    parser.add_argument("--reset-state", action="store_true", help="Forget local upload progress and replay every CSV row with idempotent upserts.")
    parser.add_argument("--replay-complete", action="store_true", help="Replay all remaining table state even if prior state says the load completed.")
    parser.add_argument("--continue-on-error", action="store_true", help="Quarantine irreducible single-row DB errors and continue. Default is fail-fast.")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-upload exact/at-least database row-count verification.")
    parser.add_argument("--skip-local-validation", action="store_true", help="Skip the full typed row validation pass (headers/manifest are still checked).")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.batch_rows <= 0:
        parser.error("--batch-rows must be positive")
    if args.max_payload_bytes < 1024:
        parser.error("--max-payload-bytes must be at least 1024")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.retries <= 0:
        parser.error("--retries must be positive")
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        report = run_upload(args)
    except KeyboardInterrupt:
        LOG.warning("Interrupted. Completed REST batches are committed and upload state was saved; rerun the same command to resume.")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        LOG.error("Supabase upload failed: %s", exc)
        if args.log_level == "DEBUG":
            LOG.exception("Detailed failure")
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if int(report.get("failed_rows_this_run", 0)) > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
