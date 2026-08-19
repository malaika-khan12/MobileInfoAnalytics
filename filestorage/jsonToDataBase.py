#!/usr/bin/env python3
"""Upload organised template_v2 JSON files into Supabase reliably.

This is the direct-JSON entry point for MobileInfoAnalytics.  It intentionally
reuses the already-tested ``jsonToCsv.py`` normalization/matching logic and the
same ``csvToDataBase.py`` Supabase uploader rather than maintaining a second,
divergent interpretation of template_v2.

Pipeline used by this command:

    mobiles_organised/*.json
        -> jsonToCsv.run_conversion() into a private resumable cache
        -> csvToDataBase.run_upload()
        -> Supabase PostgreSQL

Why this is preferable to calling ``etl.ingest_template_v2_json`` once per JSON:
* both CSV->DB and JSON->DB produce the same relational database
* GSMArena remains canonical specs rather than becoming a marketplace listing
* price currency semantics remain identical to the successful jsonToCsv run
* deterministic IDs preserve all FK links and make uploads idempotent/resumable
* thousands of records are uploaded in bounded bulk REST batches rather than
  thousands of individual RPC round trips

The script requires the sibling files ``jsonToCsv.py`` and ``csvToDataBase.py``.
No third-party Python packages are required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Sequence


LOG = logging.getLogger("jsonToDataBase")
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name.lower() == "filestorage" else Path.cwd()
DEFAULT_INPUT_DIR = PROJECT_ROOT / "filestorage" / "mobiles_organised"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "filestorage" / ".json_database_csv_cache"
CACHE_META_NAME = "json_database_source.json"


def import_pipeline_modules() -> tuple[Any, Any]:
    # When run as `python filestorage/jsonToDataBase.py`, Python normally puts
    # filestorage/ first in sys.path.  Add it explicitly for IDE/module runners.
    script_dir = str(SCRIPT_DIR)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    try:
        import jsonToCsv  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            f"Missing sibling {SCRIPT_DIR / 'jsonToCsv.py'}. Keep jsonToDataBase.py "
            "beside the successfully tested jsonToCsv.py converter."
        ) from exc
    try:
        import csvToDataBase  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            f"Missing sibling {SCRIPT_DIR / 'csvToDataBase.py'}. Keep both new database "
            "upload scripts in filestorage/."
        ) from exc
    if not hasattr(jsonToCsv, "run_conversion"):
        raise RuntimeError("jsonToCsv.py does not expose run_conversion(); wrong converter version")
    if not hasattr(csvToDataBase, "run_upload"):
        raise RuntimeError("csvToDataBase.py does not expose run_upload(); wrong uploader version")
    return jsonToCsv, csvToDataBase


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def selected_json_paths(input_dir: Path, sites: Sequence[str]) -> list[Path]:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Organised JSON directory does not exist: {input_dir}")
    selected = {site.strip().lower() for site in sites if site.strip()}
    paths: list[Path] = []
    for site_dir in sorted(path for path in input_dir.iterdir() if path.is_dir()):
        if selected and site_dir.name.lower() not in selected:
            continue
        paths.extend(
            sorted(
                path for path in site_dir.glob("*.json")
                if path.is_file() and not path.name.startswith("_")
            )
        )
    if not paths:
        raise FileNotFoundError(f"No organised JSON files found under {input_dir}")
    return paths


def fast_source_fingerprint(input_dir: Path, sites: Sequence[str]) -> tuple[str, int]:
    """Fingerprint path/size/mtime without rereading all JSON bytes.

    jsonToCsv performs full JSON parsing immediately afterwards when conversion
    is needed.  On resume, this metadata fingerprint makes cache validation fast.
    """
    digest = hashlib.sha256()
    paths = selected_json_paths(input_dir, sites)
    for path in paths:
        stat = path.stat()
        rel = path.relative_to(input_dir).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode())
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode())
        digest.update(b"\n")
    return digest.hexdigest(), len(paths)


def cache_meta_path(cache_dir: Path) -> Path:
    return cache_dir / "_manifest" / CACHE_META_NAME


def read_cache_meta(cache_dir: Path) -> dict[str, Any] | None:
    path = cache_meta_path(cache_dir)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Invalid JSON-to-DB cache metadata {path}: {exc}") from exc
    return value if isinstance(value, dict) else None


def uploader_state_exists(cache_dir: Path) -> bool:
    return (cache_dir / "_manifest" / "database_upload_state.json").is_file()


def build_converter_args(args: argparse.Namespace, cache_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(
        input_dir=args.input_dir.resolve(),
        output_dir=cache_dir.resolve(),
        site=list(args.site),
        canonical_source=args.canonical_source,
        currency=args.currency,
        strict=True,
        log_level=args.log_level,
    )


def ensure_csv_cache(args: argparse.Namespace, jsonToCsv: Any) -> dict[str, Any]:
    input_dir = args.input_dir.resolve()
    cache_dir = args.cache_dir.resolve()
    fingerprint, file_count = fast_source_fingerprint(input_dir, args.site)
    current_meta = read_cache_meta(cache_dir)
    settings = {
        "source_fingerprint": fingerprint,
        "source_file_count": file_count,
        "input_dir": str(input_dir),
        "sites": sorted(args.site),
        "canonical_source": args.canonical_source,
        "currency": args.currency.upper(),
    }
    cache_matches = bool(
        current_meta
        and all(current_meta.get(key) == value for key, value in settings.items())
        and (cache_dir / "_manifest" / "manifest.json").is_file()
    )

    if args.rebuild_cache:
        cache_matches = False

    if cache_matches:
        LOG.info("JSON source unchanged; reusing converted upload cache: %s", cache_dir)
        return {"reused": True, **settings}

    if uploader_state_exists(cache_dir):
        raise RuntimeError(
            "The organised JSON source/cache settings changed after a database upload had already "
            "started. Refusing to silently mix datasets in the target database. Either restore the "
            "original JSON set and resume, or intentionally start a new clean database/import and "
            "remove the cache directory first."
        )

    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    LOG.info("Building relational upload cache from %d organised JSON files", file_count)
    manifest = jsonToCsv.run_conversion(build_converter_args(args, cache_dir))
    meta = {
        **settings,
        "generated_at_epoch": time.time(),
        "converter_manifest": manifest,
    }
    atomic_json(cache_meta_path(cache_dir), meta)
    LOG.info(
        "JSON conversion cache complete: records=%s products=%s listings=%s",
        manifest.get("records_written"), manifest.get("products"), manifest.get("marketplace_listings"),
    )
    return {"reused": False, **settings}


def build_uploader_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        csv_root=args.cache_dir,
        batch_rows=args.batch_rows,
        max_payload_bytes=args.max_payload_bytes,
        timeout=args.timeout,
        retries=args.retries,
        dry_run=args.dry_run,
        preflight_only=args.preflight_only,
        allow_existing=args.allow_existing,
        reset_state=args.reset_state,
        replay_complete=args.replay_complete,
        continue_on_error=args.continue_on_error,
        no_verify=args.no_verify,
        skip_local_validation=args.skip_local_validation,
        log_level=args.log_level,
    )


def run_json_upload(args: argparse.Namespace) -> dict[str, Any]:
    jsonToCsv, csvToDataBase = import_pipeline_modules()
    cache_info = ensure_csv_cache(args, jsonToCsv)
    upload_report = csvToDataBase.run_upload(build_uploader_args(args))
    return {
        "entrypoint": "jsonToDataBase",
        "input_dir": str(args.input_dir.resolve()),
        "cache_dir": str(args.cache_dir.resolve()),
        "cache": cache_info,
        "database": upload_report,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert organised template_v2 JSON and resumably upload it to Supabase."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--site", action="append", default=[], help="Process only this source domain; repeatable.")
    parser.add_argument("--canonical-source", default="gsmarena.com")
    parser.add_argument("--currency", default="PKR")
    parser.add_argument("--rebuild-cache", action="store_true", help="Force JSON->CSV cache regeneration before upload (not allowed after an upload has started).")

    # Same database safety/reliability switches as csvToDataBase.py.
    parser.add_argument("--batch-rows", type=int, default=250)
    parser.add_argument("--max-payload-bytes", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--dry-run", action="store_true", help="Convert/validate locally only; no credentials or network.")
    parser.add_argument("--preflight-only", action="store_true", help="Convert/validate, then test Supabase credentials/schemas/counts without writes.")
    parser.add_argument("--allow-existing", action="store_true")
    parser.add_argument("--reset-state", action="store_true")
    parser.add_argument("--replay-complete", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--skip-local-validation", action="store_true")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.batch_rows <= 0:
        parser.error("--batch-rows must be positive")
    if args.max_payload_bytes < 1024:
        parser.error("--max-payload-bytes must be at least 1024")
    if args.timeout <= 0 or args.retries <= 0:
        parser.error("--timeout and --retries must be positive")
    args.currency = args.currency.strip().upper()
    if len(args.currency) != 3 or not args.currency.isalpha():
        parser.error("--currency must be a 3-letter code")

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        report = run_json_upload(args)
    except KeyboardInterrupt:
        LOG.warning("Interrupted. Any committed database batches remain resumable; rerun the same command.")
        return 130
    except Exception as exc:  # noqa: BLE001
        LOG.error("JSON-to-Supabase upload failed: %s", exc)
        if args.log_level == "DEBUG":
            LOG.exception("Detailed failure")
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    db = report.get("database", {})
    return 2 if int(db.get("failed_rows_this_run", 0)) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
