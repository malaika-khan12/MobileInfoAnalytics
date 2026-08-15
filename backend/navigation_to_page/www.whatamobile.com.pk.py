"""
Manifest-based, resumable Playwright navigator for WhatAMobile.com.pk.

The navigator reads:
    filestorage/sitemap_mobile/whatamobile.com.pk.json

The manifest is produced by:
    filestorage/FilterMobileUrls.py

Workflow:

    sitemap
        ↓
    FilterMobileUrls.py
        ↓
    1812 product URLs
        ↓
    this navigator
        ↓
    WhatamobileScraper
        ↓
    filestorage/mobiles/whatamobile.com.pk/

The navigator does NOT crawl the catalogue to discover products.
Product positions are determined by the manifest order.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import random
import sys
import time

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import urlparse


LOG = logging.getLogger("whatamobile.navigator")


# ============================================================================
# PATHS
# ============================================================================

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MANIFEST = (
    ROOT
    / "filestorage"
    / "sitemap_mobile"
    / "whatamobile.com.pk.json"
)

DEFAULT_OUTPUT = (
    ROOT
    / "filestorage"
    / "mobiles"
    / "whatamobile.com.pk"
)

SCRAPER_PATH = (
    ROOT
    / "backend"
    / "scrapers"
    / "www.whatamobile.com.pk.py"
)

INVALID_FILENAME = __import__(
    "re"
).compile(
    r'[<>:"/\\|?*\x00-\x1f]'
)


# ============================================================================
# URL HELPERS
# ============================================================================

def canonical_site(
    value: str,
) -> str:

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

    if host.startswith("www."):
        host = host[4:]

    return host


def is_whatamobile_product_url(
    url: str,
) -> bool:
    """
    Valid WhatAMobile product URL:

        https://www.whatamobile.com.pk/product/<slug>
        https://www.whatamobile.com.pk/product/<slug>/
    """

    parsed = urlparse(url)

    if (
        canonical_site(url)
        != "whatamobile.com.pk"
    ):
        return False

    if parsed.query or parsed.fragment:
        return False

    path = parsed.path.rstrip("/")

    if not path.lower().startswith(
        "/product/"
    ):
        return False

    slug = path[
        len("/product/"):
    ].strip("/")

    return bool(
        slug
        and "/" not in slug
    )


def output_filename(
    url: str,
) -> str:

    filename = urlparse(
        url
    ).path.rstrip("/").split("/")[-1]

    filename = (
        filename
        or "unknown-product"
    )

    filename = INVALID_FILENAME.sub(
        "_",
        filename,
    ).rstrip(". ")

    return (
        f"whatamobile__{filename}.json"
    )


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
        f"{random.randrange(1_000_000):06d}."
        f"tmp"
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
            payload.get(
                "MobileName"
            )
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

def positive_int(
    value: str,
) -> int:

    parsed = int(value)

    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            "value must be greater than zero"
        )

    return parsed


def nonnegative_int(
    value: str,
) -> int:

    parsed = int(value)

    if parsed < 0:
        raise argparse.ArgumentTypeError(
            "value must be zero or greater"
        )

    return parsed


def nonnegative_float(
    value: str,
) -> float:

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

        maximum = (
            minimum
            + limit
            - 1
        )

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
    """
    Load and validate the direct product URLs from the
    generated sitemap_mobile manifest.

    Important:
    - preserves manifest order
    - removes duplicates
    - accepts only actual WhatAMobile /product/ URLs
    """

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
            f"Could not read manifest "
            f"{path}: {exc}"
        ) from exc

    if not isinstance(
        data,
        dict,
    ):

        raise ValueError(
            "Manifest root must be a JSON object."
        )

    records = data.get(
        "mobile_urls",
        []
    )

    if not isinstance(
        records,
        list,
    ):

        raise ValueError(
            "Manifest 'mobile_urls' must be a list."
        )

    urls: list[str] = []
    seen: set[str] = set()

    for record in records:

        if isinstance(
            record,
            str,
        ):

            url = record

        elif isinstance(
            record,
            dict,
        ):

            url = record.get(
                "url"
            )

        else:

            continue

        if not isinstance(
            url,
            str,
        ):
            continue

        url = url.strip()

        if not url:
            continue

        if not is_whatamobile_product_url(
            url
        ):
            continue

        # Normalize only the trailing slash.
        url = url.rstrip("/")

        if url in seen:
            continue

        seen.add(url)

        urls.append(url)

    if not urls:

        raise ValueError(
            "Manifest contains no valid "
            "WhatAMobile product URLs."
        )

    return urls


# ============================================================================
# SCRAPER LOADING
# ============================================================================

_SCRAPER_CLASS = None


def load_scraper_class():

    global _SCRAPER_CLASS

    if _SCRAPER_CLASS is not None:
        return _SCRAPER_CLASS

    if not SCRAPER_PATH.is_file():

        raise FileNotFoundError(
            f"Scraper file not found:\n"
            f"{SCRAPER_PATH}"
        )

    spec = (
        importlib.util.spec_from_file_location(
            "whatamobile_scraper",
            SCRAPER_PATH,
        )
    )

    if (
        spec is None
        or spec.loader is None
    ):

        raise ImportError(
            f"Could not load scraper module "
            f"from {SCRAPER_PATH}"
        )

    module = (
        importlib.util.module_from_spec(
            spec
        )
    )

    spec.loader.exec_module(
        module
    )

    scraper_class = getattr(
        module,
        "WhatamobileScraper",
        None,
    )

    if scraper_class is None:

        raise ImportError(
            "www.whatamobile.com.pk.py must "
            "contain class WhatamobileScraper."
        )

    _SCRAPER_CLASS = scraper_class

    return scraper_class


# ============================================================================
# NAVIGATOR
# ============================================================================

class WhatAMobileNavigator:

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

    def __enter__(
        self,
    ) -> "WhatAMobileNavigator":

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

    def new_page(
        self,
        context,
    ):

        page = context.new_page()

        if not self.load_assets:

            def route_handler(
                route,
            ):

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

    # ----------------------------------------------------------------------
    # Product scraping
    # ----------------------------------------------------------------------

    def scrape_product(
        self,
        page,
        url: str,
    ) -> dict:

        if not is_whatamobile_product_url(
            url
        ):

            raise ValueError(
                f"Not a valid WhatAMobile "
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

        if (
            canonical_site(page.url)
            != "whatamobile.com.pk"
        ):

            raise RuntimeError(
                f"Unexpected redirect from "
                f"{url} to {page.url}"
            )

        # Allow the page to finish rendering, but don't
        # fail just because networkidle isn't reached.
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
                f"Empty HTML received from {url}"
            )

        scraper_class = (
            load_scraper_class()
        )

        scraper = scraper_class(
            html,
            source_url=url,
        )

        result = scraper.to_template()

        self._pause()

        if not isinstance(
            result,
            dict,
        ):

            raise RuntimeError(
                "WhatamobileScraper returned "
                "an invalid result."
            )

        if not result.get(
            "MobileName"
        ):

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

    manifest_records: int = 0

    invalid_manifest_records: int = 0

    manifest_duplicates: int = 0

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

    started_at = utc_now()

    stats = CrawlStats(
        manifest=str(
            manifest_path
        ),
        output_dir=str(
            output_dir
        ),
        started_at=started_at,
        eligible_products=len(urls),
        range_min=minimum,
        range_max=maximum,
    )

    # --------------------------------------------------------------
    # Determine selected range.
    # --------------------------------------------------------------

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
        output_dir
        / "_failures.jsonl"
    )

    summary_path = (
        output_dir
        / "_crawl_summary.json"
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

    # --------------------------------------------------------------
    # Browser.
    # --------------------------------------------------------------

    try:

        with WhatAMobileNavigator(
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

            context = (
                navigator.new_context()
            )

            try:

                for position, url in enumerate(
                    selected,
                    start=minimum,
                ):

                    target = (
                        output_dir
                        / output_filename(url)
                    )

                    # --------------------------------------------------
                    # Resume.
                    # --------------------------------------------------

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

                    # --------------------------------------------------
                    # Retry loop.
                    # --------------------------------------------------

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
                                "failed: %s",
                                position,
                                attempt,
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

                    # --------------------------------------------------
                    # Record final failure.
                    # --------------------------------------------------

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
            "Interrupted. Completed JSON files "
            "are preserved for resume."
        )

    except Exception as exc:

        stats.failed += 1

        LOG.exception(
            "Crawler failed: %s",
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

    return (
        1
        if stats.failed
        else 0
    )


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
        "eligible_products": len(
            urls
        ),
        "range_min": minimum,
        "range_max": maximum,
        "selected_products": len(
            selected
        ),
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
            "Scrape WhatAMobile product URLs "
            "from the filtered sitemap manifest."
        )
    )

    parser.add_argument(
        "url",
        nargs="?",
        help=(
            "Optional single WhatAMobile "
            "product URL."
        ),
    )

    parser.add_argument(
        "--sitemap",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=(
            "Filtered WhatAMobile manifest."
        ),
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

    if (
        args.delay_max
        < args.delay_min
    ):

        parser.error(
            "--delay-max must be greater than "
            "or equal to --delay-min"
        )

    try:

        minimum, maximum = (
            resolve_range(
                args.minimum,
                args.maximum,
                args.limit,
            )
        )

    except ValueError as exc:

        parser.error(
            str(exc)
        )

    # --------------------------------------------------------------
    # Single URL mode.
    # --------------------------------------------------------------

    if args.url:

        if not is_whatamobile_product_url(
            args.url
        ):

            parser.error(
                "URL must be a valid "
                "WhatAMobile /product/ URL."
            )

        single_urls = [
            args.url.rstrip("/")
        ]

        if args.dry_run:

            return run_dry_run(
                Path(
                    args.url
                ),
                single_urls,
                1,
                1,
            )

        return crawl_manifest(
            Path(args.url),
            single_urls,
            args.output_dir,
            args,
            1,
            1,
        )

    # --------------------------------------------------------------
    # Manifest mode.
    # --------------------------------------------------------------

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
    sys.exit(
        main()
    )