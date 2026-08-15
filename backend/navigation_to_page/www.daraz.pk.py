"""
Resumable Playwright crawler for Daraz.pk smartphones.

Daraz's sitemap contains opaque product URLs and cannot reliably identify
which products are mobile phones.

This navigator therefore uses the Daraz smartphones catalogue:

    https://www.daraz.pk/smartphones/

It only accepts product links whose anchor belongs to Daraz's actual
product-card structure.

The navigator:
- discovers smartphone product URLs
- follows catalogue pagination
- deduplicates product URLs
- preserves discovery order
- supports --min / --max / --limit
- skips existing valid JSON files unless --force
- retries failed products
- writes _failures.jsonl
- writes _crawl_summary.json
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
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


LOG = logging.getLogger("daraz.navigator")

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CATEGORY = (
    "https://www.daraz.pk/smartphones/"
)

DEFAULT_OUTPUT = (
    ROOT
    / "filestorage"
    / "mobiles"
    / "daraz.pk"
)

SCRAPER_PATH = (
    ROOT
    / "backend"
    / "scrapers"
    / "www.daraz.pk.py"
)

INVALID_FILENAME = re.compile(
    r'[<>:"/\\|?*\x00-\x1f]'
)

PRODUCT_RE = re.compile(
    r"^/products/"
    r"[^/?#]+-i\d+"
    r"(?:-s\d+)?"
    r"\.html/?$",
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


def normalize_url(url: str) -> str:
    parsed = urlparse(url)

    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc,
            parsed.path.rstrip("/") or "/",
            "",
            "",
            "",
        )
    )


def is_daraz_product_url(url: str) -> bool:
    parsed = urlparse(url)

    if canonical_site(url) != "daraz.pk":
        return False

    if parsed.fragment:
        return False

    return bool(
        PRODUCT_RE.fullmatch(
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
            f"Could not derive filename from {url!r}"
        )

    return f"daraz__{name}.json"


def category_page_url(
    category_url: str,
    page_number: int,
) -> str:
    parsed = urlparse(
        category_url
    )

    if page_number == 1:
        return normalize_url(
            category_url
        )

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    query["page"] = [
        str(page_number)
    ]

    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc,
            parsed.path,
            "",
            urlencode(
                query,
                doseq=True,
            ),
            "",
        )
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
        isinstance(payload, dict)
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
# SCRAPER LOADING
# ============================================================================

_SCRAPER_CLASS = None


def load_scraper_class():

    global _SCRAPER_CLASS

    if _SCRAPER_CLASS is not None:
        return _SCRAPER_CLASS

    if not SCRAPER_PATH.is_file():
        raise FileNotFoundError(
            f"Daraz scraper not found:\n{SCRAPER_PATH}"
        )

    module_name = "daraz_scraper_runtime"

    spec = importlib.util.spec_from_file_location(
        module_name,
        SCRAPER_PATH,
    )

    if (
        spec is None
        or spec.loader is None
    ):
        raise ImportError(
            f"Could not load Daraz scraper "
            f"from {SCRAPER_PATH}"
        )

    module = importlib.util.module_from_spec(
        spec
    )

    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(
            module
        )
    except Exception:
        sys.modules.pop(
            module_name,
            None,
        )
        raise

    scraper_class = getattr(
        module,
        "DarazScraper",
        None,
    )

    if scraper_class is None:
        raise ImportError(
            "www.daraz.pk.py must contain "
            "class DarazScraper"
        )

    _SCRAPER_CLASS = scraper_class

    return scraper_class


# ============================================================================
# NAVIGATOR
# ============================================================================

class DarazNavigator:

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
        max_category_pages: int,
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
        self.max_category_pages = (
            max_category_pages
        )

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
                "Run 'python -m playwright install chromium'."
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

    # ------------------------------------------------------------------
    # CATEGORY DISCOVERY
    # ------------------------------------------------------------------

    def discover_category_page(
        self,
        page,
        url: str,
    ) -> list[str]:

        LOG.info(
            "Opening category: %s",
            url,
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
                f"HTTP {response.status} for {url}"
            )

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=8000,
            )
        except Exception:
            pass

        # We specifically use Daraz's product-card
        # anchor structure observed on /smartphones/.
        #
        # Actual card anchors:
        #     parent class = RfADt
        #
        # Image anchors nearby use:
        #     parent class = _95X4G
        #
        # Only the RfADt anchor is accepted.

        hrefs = page.eval_on_selector_all(
            "a[href]",
            """
            els => els
              .map(a => ({
                  href: a.getAttribute("href"),
                  parentClass: a.parentElement
                      ? (a.parentElement.className || "")
                      : "",
                  grandParentClass: a.parentElement
                      && a.parentElement.parentElement
                      ? (a.parentElement.parentElement.className || "")
                      : "",
                  text: (a.innerText || "").trim()
              }))
              .filter(x =>
                  x.href &&
                  (
                      String(x.parentClass).includes("RfADt") ||
                      String(x.grandParentClass).includes("RfADt")
                  )
              )
            """,
        )

        results = []
        seen = set()

        for item in hrefs:

            if not isinstance(
                item,
                dict,
            ):
                continue

            href = item.get(
                "href"
            )

            if not isinstance(
                href,
                str,
            ):
                continue

            href = href.strip()

            if not href:
                continue

            if href.startswith(
                "//"
            ):
                href = "https:" + href

            elif href.startswith(
                "/"
            ):
                href = (
                    "https://www.daraz.pk"
                    + href
                )

            elif not href.startswith(
                "http"
            ):
                continue

            if not is_daraz_product_url(
                href
            ):
                continue

            normalized = normalize_url(
                href
            )

            if normalized in seen:
                continue

            seen.add(
                normalized
            )

            results.append(
                normalized
            )

        self._pause()

        return results

    # ------------------------------------------------------------------
    # PAGINATION
    # ------------------------------------------------------------------

    def discover_all_products(
        self,
        context,
        category_url: str,
    ) -> list[str]:

        all_products = []
        seen_products = set()
        seen_pages = set()

        empty_pages = 0

        for page_number in range(
            1,
            self.max_category_pages + 1,
        ):

            current_url = category_page_url(
                category_url,
                page_number,
            )

            if current_url in seen_pages:
                break

            seen_pages.add(
                current_url
            )

            listing_page = self.new_page(
                context
            )

            try:

                products = (
                    self.discover_category_page(
                        listing_page,
                        current_url,
                    )
                )

            finally:

                listing_page.close()

            new_count = 0

            for product_url in products:

                if product_url in seen_products:
                    continue

                seen_products.add(
                    product_url
                )

                all_products.append(
                    product_url
                )

                new_count += 1

            LOG.info(
                "CATEGORY PAGE %d: discovered=%d "
                "new=%d total=%d",
                page_number,
                len(products),
                new_count,
                len(all_products),
            )

            if new_count == 0:
                empty_pages += 1
            else:
                empty_pages = 0

            # Two consecutive pages without a new product
            # means pagination has effectively ended.
            if empty_pages >= 2:
                break

        return all_products

    # ------------------------------------------------------------------
    # PRODUCT SCRAPING
    # ------------------------------------------------------------------

    def scrape_product(
        self,
        page,
        url: str,
    ) -> dict:

        if not is_daraz_product_url(
            url
        ):
            raise ValueError(
                f"Invalid Daraz product URL: {url}"
            )

        LOG.info(
            "PRODUCT: %s",
            url,
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

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=8000,
            )
        except Exception:
            pass

        try:
            page.wait_for_selector(
                "h1",
                timeout=self.selector_timeout_ms,
            )
        except Exception:
            pass

        if canonical_site(
            page.url
        ) != "daraz.pk":
            raise RuntimeError(
                f"Unexpected redirect from "
                f"{url} to {page.url}"
            )

        html = page.content()

        if not html.strip():
            raise RuntimeError(
                f"Empty HTML returned from {url}"
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
                "DarazScraper returned "
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

    categories: int
    discovered: int
    selected_urls: int
    started_at: str

    finished_at: Optional[str] = None

    succeeded: int = 0
    skipped: int = 0
    failed: int = 0

    interrupted: bool = False


# ============================================================================
# DISCOVERY
# ============================================================================

def discover_products(
    category_urls: list[str],
    args,
) -> list[str]:

    all_products = []
    seen = set()

    with DarazNavigator(
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
        max_category_pages=(
            args.max_category_pages
        ),
    ) as navigator:

        context = navigator.new_context()

        try:

            for category_url in category_urls:

                category_products = (
                    navigator.discover_all_products(
                        context,
                        category_url,
                    )
                )

                for url in category_products:

                    if url in seen:
                        continue

                    seen.add(url)
                    all_products.append(url)

        finally:
            context.close()

    return all_products


# ============================================================================
# CRAWL
# ============================================================================

def crawl(
    category_urls: list[str],
    output_dir: Path,
    args,
    minimum: int,
    maximum: Optional[int],
) -> int:

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

    stats = CrawlStats(
        categories=len(
            category_urls
        ),
        discovered=0,
        selected_urls=0,
        started_at=utc_now(),
    )

    try:

        all_products = discover_products(
            category_urls,
            args,
        )

        stats.discovered = len(
            all_products
        )

        selected = all_products[
            minimum - 1:
            maximum
        ]

        stats.selected_urls = len(
            selected
        )

        LOG.info(
            "DISCOVERY COMPLETE: "
            "categories=%d unique_products=%d "
            "selected=%d",
            len(category_urls),
            len(all_products),
            len(selected),
        )

        with DarazNavigator(
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
            max_category_pages=(
                args.max_category_pages
            ),
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

                    last_error = None

                    for attempt in range(
                        1,
                        args.retries + 2,
                    ):

                        detail = None

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

                            detail = (
                                navigator.new_page(
                                    context
                                )
                            )

                            result = (
                                navigator.scrape_product(
                                    detail,
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

                            if detail is not None:

                                try:
                                    detail.close()
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

                context.close()

    except KeyboardInterrupt:

        stats.interrupted = True

        LOG.warning(
            "Interrupted. Existing completed "
            "files are preserved."
        )

    except Exception as exc:

        stats.failed += 1

        LOG.exception(
            "Daraz crawler failed: %s",
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
            "SUMMARY: categories=%d "
            "discovered=%d selected=%d "
            "saved=%d skipped=%d failed=%d "
            "interrupted=%s",
            stats.categories,
            stats.discovered,
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
    category_urls: list[str],
    args,
    minimum: int,
    maximum: Optional[int],
) -> int:

    try:

        products = discover_products(
            category_urls,
            args,
        )

    except Exception as exc:

        LOG.error(
            "Dry run failed: %s",
            exc,
        )

        return 1

    selected = products[
        minimum - 1:
        maximum
    ]

    print(
        json.dumps(
            {
                "categories": category_urls,
                "discovered_products": len(
                    products
                ),
                "range_min": minimum,
                "range_max": maximum,
                "selected_products": len(
                    selected
                ),
                "sample": selected[:10],
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    return 0


# ============================================================================
# CLI
# ============================================================================

def build_parser():

    parser = argparse.ArgumentParser(
        description=(
            "Crawl Daraz.pk smartphone "
            "products into template JSON."
        )
    )

    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        default=None,
        help=(
            "Daraz category URL. Defaults "
            "to /smartphones/."
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    parser.add_argument(
        "--min",
        dest="minimum",
        type=positive_int,
        default=1,
    )

    parser.add_argument(
        "--max",
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
        "--max-category-pages",
        type=positive_int,
        default=100,
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

    category_urls = (
        args.categories
        if args.categories
        else [
            DEFAULT_CATEGORY
        ]
    )

    validated = []

    for url in category_urls:

        if canonical_site(
            url
        ) != "daraz.pk":
            parser.error(
                f"Invalid Daraz URL: {url}"
            )

        validated.append(
            normalize_url(url)
        )

    if args.dry_run:

        return run_dry_run(
            validated,
            args,
            minimum,
            maximum,
        )

    return crawl(
        validated,
        args.output_dir,
        args,
        minimum,
        maximum,
    )


if __name__ == "__main__":
    sys.exit(
        main()
    )