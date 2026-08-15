"""
Manifest-based, resumable Playwright navigator for Mega.pk.

Reads:
    filestorage/sitemap_mobile/mega.pk.json

The manifest contains direct Mega.pk mobile product URLs:

    /mobiles_products/<id>/<slug>.html

The navigator:
- preserves manifest order
- supports --min / --max
- skips existing valid files unless --force
- retries failed pages
- writes _failures.jsonl
- writes _crawl_summary.json
- does NOT crawl the Mega catalogue
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import random
import re
import sys
import time

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlparse


LOG = logging.getLogger("mega.navigator")


# ============================================================================
# PATHS
# ============================================================================

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MANIFEST = (
    ROOT
    / "filestorage"
    / "sitemap_mobile"
    / "mega.pk.json"
)

DEFAULT_OUTPUT = (
    ROOT
    / "filestorage"
    / "mobiles"
    / "mega.pk"
)

SCRAPER_PATH = (
    ROOT
    / "backend"
    / "scrapers"
    / "www.mega.pk.py"
)

INVALID_FILENAME = re.compile(
    r'[<>:"/\\|?*\x00-\x1f]'
)

PRODUCT_PATH_RE = re.compile(
    r"^/mobiles_products/"
    r"\d+/"
    r"[^/?#]+\.html/?$",
    re.IGNORECASE,
)


# ============================================================================
# URL HELPERS
# ============================================================================

def canonical_site(value: str) -> str:
    parsed = urlparse(
        value
        if "://" in value
        else f"https://{value}"
    )

    host = (
        parsed.netloc
        .lower()
        .split("@")[-1]
        .split(":")[0]
    )

    return re.sub(
        r"^www\.",
        "",
        host,
    )


def is_mega_product_url(url: str) -> bool:
    parsed = urlparse(url)

    if canonical_site(url) != "mega.pk":
        return False

    if parsed.query or parsed.fragment:
        return False

    return bool(
        PRODUCT_PATH_RE.fullmatch(
            parsed.path
        )
    )


def output_filename(url: str) -> str:
    name = Path(
        urlparse(url).path
    ).name

    name = INVALID_FILENAME.sub(
        "_",
        name,
    ).rstrip(". ")

    if not name:
        raise ValueError(
            f"Could not derive output filename from {url!r}"
        )

    return f"mega__{name}.json"


# ============================================================================
# FILE HELPERS
# ============================================================================

def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )


def atomic_write_json(
    path: Path,
    payload: dict,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        f"{path.name}."
        f"{os.getpid()}."
        f"{random.randrange(1_000_000):06d}.tmp"
    )

    try:

        temporary.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        os.replace(
            temporary,
            path,
        )

    finally:

        if temporary.exists():
            temporary.unlink()


def valid_existing_output(
    path: Path,
) -> bool:

    if not path.is_file():
        return False

    try:

        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return False

    return (
        isinstance(
            payload,
            dict,
        )
        and bool(
            payload.get("MobileName")
        )
    )


def append_json_line(
    path: Path,
    payload: dict,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
        newline="\n",
    ) as handle:

        handle.write(
            json.dumps(
                payload,
                ensure_ascii=False,
            )
            + "\n"
        )


# ============================================================================
# ARGUMENT HELPERS
# ============================================================================

def positive_int(value: str) -> int:
    parsed = int(value)

    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            "value must be greater than zero"
        )

    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)

    if parsed < 0:
        raise argparse.ArgumentTypeError(
            "value must be zero or greater"
        )

    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)

    if parsed < 0:
        raise argparse.ArgumentTypeError(
            "value must be zero or greater"
        )

    return parsed


def resolve_range(
    minimum: int,
    maximum: Optional[int],
    limit: Optional[int],
) -> tuple[int, Optional[int]]:

    if (
        limit is not None
        and maximum is not None
    ):
        raise ValueError(
            "--limit cannot be combined with --max"
        )

    if limit is not None:
        maximum = minimum + limit - 1

    if (
        maximum is not None
        and maximum < minimum
    ):
        raise ValueError(
            "--max must be greater than "
            "or equal to --min"
        )

    return minimum, maximum


# ============================================================================
# MANIFEST
# ============================================================================

def load_manifest(
    path: Path,
) -> list[str]:

    if not path.is_file():
        raise FileNotFoundError(
            f"Manifest not found:\n{path}"
        )

    try:

        data = json.loads(
            path.read_text(
                encoding="utf-8-sig"
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:

        raise ValueError(
            f"Could not load manifest "
            f"{path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "Manifest root must be a JSON object."
        )

    records = data.get(
        "mobile_urls",
        [],
    )

    if not isinstance(records, list):
        raise ValueError(
            "Manifest 'mobile_urls' must be a list."
        )

    urls: list[str] = []
    seen: set[str] = set()

    for record in records:

        if isinstance(record, str):
            url = record

        elif isinstance(record, dict):
            url = record.get("url")

        else:
            continue

        if not isinstance(url, str):
            continue

        url = url.strip()

        if not url:
            continue

        if not is_mega_product_url(url):
            continue

        url = url.rstrip("/")

        if url in seen:
            continue

        seen.add(url)
        urls.append(url)

    if not urls:
        raise ValueError(
            "Manifest contains no valid "
            "Mega.pk mobile product URLs."
        )

    return urls


# ============================================================================
# SCRAPER LOADING
# ============================================================================

_SCRAPER_CLASS = None


def load_scraper_class():
    """
    Dynamically import the Mega scraper.

    Important:
    Register the module in sys.modules BEFORE exec_module().
    This is required for dynamically loaded modules that use
    decorators/features which consult sys.modules.
    """

    global _SCRAPER_CLASS

    if _SCRAPER_CLASS is not None:
        return _SCRAPER_CLASS

    if not SCRAPER_PATH.is_file():
        raise FileNotFoundError(
            f"Mega scraper not found:\n{SCRAPER_PATH}"
        )

    module_name = "mega_scraper_runtime"

    spec = importlib.util.spec_from_file_location(
        module_name,
        SCRAPER_PATH,
    )

    if (
        spec is None
        or spec.loader is None
    ):
        raise ImportError(
            f"Could not load Mega scraper "
            f"from {SCRAPER_PATH}"
        )

    module = importlib.util.module_from_spec(
        spec
    )

    # --------------------------------------------------------------
    # Critical fix:
    # make the module visible to Python before exec_module().
    # --------------------------------------------------------------

    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)

    except Exception:
        # Do not leave a broken partially loaded module behind.
        sys.modules.pop(
            module_name,
            None,
        )
        raise

    scraper_class = getattr(
        module,
        "MegaScraper",
        None,
    )

    if scraper_class is None:
        raise ImportError(
            "www.mega.pk.py must contain "
            "class MegaScraper"
        )

    _SCRAPER_CLASS = scraper_class

    return scraper_class


# ============================================================================
# NAVIGATOR
# ============================================================================

class MegaNavigator:

    BLOCKED_RESOURCE_TYPES = {
        "image",
        "font",
        "media",
    }

    def __init__(
        self,
        *,
        headless: bool,
        navigation_timeout_ms: int,
        selector_timeout_ms: int,
        delay_min: float,
        delay_max: float,
        load_assets: bool,
    ) -> None:

        self.headless = headless

        self.navigation_timeout_ms = (
            navigation_timeout_ms
        )

        self.selector_timeout_ms = (
            selector_timeout_ms
        )

        self.delay_min = delay_min
        self.delay_max = delay_max
        self.load_assets = load_assets

        self._playwright = None
        self.browser = None

    def __enter__(self):
        try:

            from playwright.sync_api import (
                sync_playwright
            )

        except ImportError as exc:

            raise RuntimeError(
                "Playwright is not installed. "
                "Install requirements and run "
                "'python -m playwright install chromium'."
            ) from exc

        self._playwright = (
            sync_playwright().start()
        )

        self.browser = (
            self._playwright.chromium.launch(
                headless=self.headless
            )
        )

        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:

        if self.browser is not None:

            try:
                self.browser.close()
            except Exception:
                pass

            self.browser = None

        if self._playwright is not None:

            try:
                self._playwright.stop()
            except Exception:
                pass

            self._playwright = None

    def _pause(self) -> None:

        if self.delay_max <= 0:
            return

        time.sleep(
            random.uniform(
                self.delay_min,
                self.delay_max,
            )
        )

    def new_context(self):

        if self.browser is None:
            raise RuntimeError(
                "Browser is not running."
            )

        return self.browser.new_context(
            locale="en-PK",
            viewport={
                "width": 1366,
                "height": 900,
            },
            service_workers="block",
        )

    def new_page(self, context):

        page = context.new_page()

        if not self.load_assets:

            def route_handler(route):

                if (
                    route.request.resource_type
                    in self.BLOCKED_RESOURCE_TYPES
                ):
                    route.abort()
                else:
                    route.continue_()

            page.route(
                "**/*",
                route_handler,
            )

        return page

    def scrape_product(
        self,
        page,
        url: str,
    ) -> dict:

        if not is_mega_product_url(url):
            raise ValueError(
                f"Not a valid Mega.pk mobile "
                f"product URL: {url}"
            )

        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self.navigation_timeout_ms,
        )

        if (
            response is not None
            and response.status >= 400
        ):
            raise RuntimeError(
                f"HTTP {response.status} "
                f"while loading {url}"
            )

        if canonical_site(page.url) != "mega.pk":
            raise RuntimeError(
                f"Unexpected redirect from "
                f"{url} to {page.url}"
            )

        try:
            page.wait_for_selector(
                "h1",
                timeout=self.selector_timeout_ms,
            )
        except Exception:
            pass

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=5000,
            )
        except Exception:
            pass

        html = page.content()

        if not html.strip():
            raise RuntimeError(
                f"Empty HTML returned from {url}"
            )

        scraper_class = load_scraper_class()

        scraper = scraper_class(
            html,
            source_url=url,
        )

        result = scraper.to_template()

        self._pause()

        if not isinstance(result, dict):
            raise RuntimeError(
                "MegaScraper returned "
                "an invalid result."
            )

        if not result.get("MobileName"):
            raise RuntimeError(
                f"Scraper produced no "
                f"MobileName for {url}"
            )

        return result


# ============================================================================
# STATS
# ============================================================================

@dataclass
class CrawlStats:

    manifest: str
    output_dir: str
    started_at: str

    finished_at: Optional[str] = None

    eligible_products: int = 0

    range_min: int = 1
    range_max: Optional[int] = None

    selected_urls: int = 0

    succeeded: int = 0
    skipped: int = 0
    failed: int = 0

    interrupted: bool = False


# ============================================================================
# CRAWL
# ============================================================================

def crawl_manifest(
    manifest_path: Path,
    urls: list[str],
    output_dir: Path,
    args,
    minimum: int,
    maximum: Optional[int],
) -> int:

    stats = CrawlStats(
        manifest=str(manifest_path),
        output_dir=str(output_dir),
        started_at=utc_now(),
        eligible_products=len(urls),
        range_min=minimum,
        range_max=maximum,
    )

    selected = urls[
        minimum - 1:
        maximum
    ]

    stats.selected_urls = len(
        selected
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    failures_path = (
        output_dir / "_failures.jsonl"
    )

    summary_path = (
        output_dir / "_crawl_summary.json"
    )

    LOG.info(
        "Manifest: %s",
        manifest_path,
    )

    LOG.info(
        "Eligible products: %d",
        len(urls),
    )

    LOG.info(
        "Selected range %d-%s: %d products",
        minimum,
        (
            maximum
            if maximum is not None
            else "end"
        ),
        len(selected),
    )

    try:

        with MegaNavigator(
            headless=not args.headed,
            navigation_timeout_ms=(
                args.navigation_timeout_ms
            ),
            selector_timeout_ms=(
                args.selector_timeout_ms
            ),
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            load_assets=args.load_assets,
        ) as navigator:

            context = navigator.new_context()

            try:

                for position, url in enumerate(
                    selected,
                    start=minimum,
                ):

                    target = (
                        output_dir
                        / output_filename(url)
                    )

                    if (
                        not args.force
                        and valid_existing_output(
                            target
                        )
                    ):

                        stats.skipped += 1

                        LOG.info(
                            "[%d%s] SKIP %s",
                            position,
                            (
                                f"/{maximum}"
                                if maximum is not None
                                else ""
                            ),
                            target.name,
                        )

                        continue

                    last_error: Optional[
                        BaseException
                    ] = None

                    for attempt in range(
                        1,
                        args.retries + 2,
                    ):

                        detail_page = None

                        try:

                            LOG.info(
                                "[%d%s] FETCH %s "
                                "(attempt %d/%d)",
                                position,
                                (
                                    f"/{maximum}"
                                    if maximum is not None
                                    else ""
                                ),
                                url,
                                attempt,
                                args.retries + 1,
                            )

                            detail_page = (
                                navigator.new_page(
                                    context
                                )
                            )

                            result = (
                                navigator.scrape_product(
                                    detail_page,
                                    url,
                                )
                            )

                            atomic_write_json(
                                target,
                                result,
                            )

                            stats.succeeded += 1

                            LOG.info(
                                "[%d] SAVED %s",
                                position,
                                target.name,
                            )

                            last_error = None
                            break

                        except KeyboardInterrupt:
                            raise

                        except Exception as exc:

                            last_error = exc

                            LOG.warning(
                                "[%d] attempt %d "
                                "failed for %s: %s",
                                position,
                                attempt,
                                url,
                                exc,
                            )

                            if (
                                attempt
                                <= args.retries
                            ):

                                time.sleep(
                                    min(
                                        2.0 ** (
                                            attempt - 1
                                        ),
                                        10.0,
                                    )
                                )

                        finally:

                            if detail_page is not None:

                                try:
                                    detail_page.close()
                                except Exception:
                                    pass

                    if last_error is not None:

                        stats.failed += 1

                        append_json_line(
                            failures_path,
                            {
                                "timestamp": utc_now(),
                                "kind": "product",
                                "url": url,
                                "output_file": str(
                                    target
                                ),
                                "attempts": (
                                    args.retries + 1
                                ),
                                "error_type": type(
                                    last_error
                                ).__name__,
                                "error": str(
                                    last_error
                                ),
                            },
                        )

            finally:

                try:
                    context.close()
                except Exception:
                    pass

    except KeyboardInterrupt:

        stats.interrupted = True

        LOG.warning(
            "Interrupted. Completed files "
            "are preserved for resume."
        )

    except Exception as exc:

        stats.failed += 1

        LOG.exception(
            "Mega crawler failed: %s",
            exc,
        )

        append_json_line(
            failures_path,
            {
                "timestamp": utc_now(),
                "kind": "crawler",
                "error_type": type(
                    exc
                ).__name__,
                "error": str(exc),
            },
        )

    finally:

        stats.finished_at = utc_now()

        atomic_write_json(
            summary_path,
            asdict(stats),
        )

        LOG.info(
            "SUMMARY: eligible=%d selected=%d "
            "saved=%d skipped=%d failed=%d "
            "interrupted=%s",
            stats.eligible_products,
            stats.selected_urls,
            stats.succeeded,
            stats.skipped,
            stats.failed,
            stats.interrupted,
        )

    if stats.interrupted:
        return 130

    return 1 if stats.failed else 0


# ============================================================================
# DRY RUN
# ============================================================================

def run_dry_run(
    manifest_path: Path,
    urls: list[str],
    minimum: int,
    maximum: Optional[int],
) -> int:

    selected = urls[
        minimum - 1:
        maximum
    ]

    payload = {
        "manifest": str(
            manifest_path
        ),
        "eligible_products": len(urls),
        "range_min": minimum,
        "range_max": maximum,
        "selected_products": len(selected),
        "sample": selected[:10],
    }

    print(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
    )

    return 0


# ============================================================================
# PARSER
# ============================================================================

def build_parser():

    parser = argparse.ArgumentParser(
        description=(
            "Scrape Mega.pk mobile products "
            "from the filtered sitemap."
        )
    )

    parser.add_argument(
        "url",
        nargs="?",
        help="Optional single Mega mobile product URL.",
    )

    parser.add_argument(
        "--sitemap",
        type=Path,
        default=DEFAULT_MANIFEST,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    parser.add_argument(
        "--min",
        "--minimum",
        dest="minimum",
        type=positive_int,
        default=1,
    )

    parser.add_argument(
        "--max",
        "--maximum",
        dest="maximum",
        type=positive_int,
    )

    parser.add_argument(
        "--limit",
        type=positive_int,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--headed",
        action="store_true",
    )

    parser.add_argument(
        "--force",
        action="store_true",
    )

    parser.add_argument(
        "--retries",
        type=nonnegative_int,
        default=2,
    )

    parser.add_argument(
        "--delay-min",
        type=nonnegative_float,
        default=2.0,
    )

    parser.add_argument(
        "--delay-max",
        type=nonnegative_float,
        default=5.0,
    )

    parser.add_argument(
        "--navigation-timeout-ms",
        type=positive_int,
        default=30_000,
    )

    parser.add_argument(
        "--selector-timeout-ms",
        type=positive_int,
        default=15_000,
    )

    parser.add_argument(
        "--load-assets",
        action="store_true",
    )

    parser.add_argument(
        "--log-level",
        choices=[
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
        ],
        default="INFO",
    )

    return parser


# ============================================================================
# MAIN
# ============================================================================

def main(
    argv: Optional[Sequence[str]] = None,
) -> int:

    parser = build_parser()

    args = parser.parse_args(
        argv
    )

    logging.basicConfig(
        level=getattr(
            logging,
            args.log_level,
        ),
        format=(
            "%(asctime)s "
            "[%(levelname)s] "
            "%(message)s"
        ),
        datefmt="%H:%M:%S",
    )

    if args.delay_max < args.delay_min:
        parser.error(
            "--delay-max must be greater than "
            "or equal to --delay-min"
        )

    try:

        minimum, maximum = resolve_range(
            args.minimum,
            args.maximum,
            args.limit,
        )

    except ValueError as exc:

        parser.error(
            str(exc)
        )

    if args.url:

        if not is_mega_product_url(
            args.url
        ):
            parser.error(
                "URL must be a valid "
                "Mega.pk /mobiles_products/ URL."
            )

        urls = [
            args.url.rstrip("/")
        ]

        manifest_path = Path(
            args.url
        )

        if args.dry_run:

            return run_dry_run(
                manifest_path,
                urls,
                1,
                1,
            )

        return crawl_manifest(
            manifest_path,
            urls,
            args.output_dir,
            args,
            1,
            1,
        )

    try:

        urls = load_manifest(
            args.sitemap
        )

    except (
        FileNotFoundError,
        ValueError,
    ) as exc:

        LOG.error(
            "%s",
            exc,
        )

        return 2

    if args.dry_run:

        return run_dry_run(
            args.sitemap,
            urls,
            minimum,
            maximum,
        )

    return crawl_manifest(
        args.sitemap,
        urls,
        args.output_dir,
        args,
        minimum,
        maximum,
    )


if __name__ == "__main__":
    sys.exit(main())