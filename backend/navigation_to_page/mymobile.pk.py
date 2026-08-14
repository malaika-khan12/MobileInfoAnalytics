"""Playwright navigation and batch crawling for MyMobile.pk."""

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
from typing import Any, Iterator, List, Optional, Sequence
from urllib.parse import unquote, urljoin, urlparse

LOG = logging.getLogger("mymobile.navigator")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "filestorage/sitemap_mobile/mymobile.pk.json"
DEFAULT_OUTPUT = ROOT / "filestorage/mobiles/mymobile.pk"
SCRAPER_PATH = ROOT / "backend/scrapers/mymobile.pk.py"

INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
PRODUCT = re.compile(r"^/products/[^/?#]+/?$", re.IGNORECASE)
CATEGORY = re.compile(r"^/category/[^/?#]+/?$", re.IGNORECASE)


def canonical_site(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    return re.sub(r"^www\.", "", host)


def is_mymobile_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        canonical_site(url) == "mymobile.pk"
        and not parsed.fragment
        and not parsed.query
    )


def product_match(url: str) -> bool:
    parsed = urlparse(url)
    return is_mymobile_url(url) and bool(PRODUCT.fullmatch(parsed.path))


def category_match(url: str) -> bool:
    parsed = urlparse(url)
    return is_mymobile_url(url) and bool(CATEGORY.fullmatch(parsed.path))


def output_filename(url: str) -> str:
    filename = unquote(Path(urlparse(url).path).name)
    filename = INVALID_FILENAME.sub("_", filename).rstrip(". ")
    if not filename:
        raise ValueError(f"Cannot derive output name from {url!r}")
    return f"mymobile__{filename}.json"


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{random.randrange(1_000_000):06d}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def valid_existing_output(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(payload, dict) and bool(payload.get("MobileName"))
    except (OSError, json.JSONDecodeError):
        return False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def resolve_range(
    minimum: int,
    maximum: Optional[int],
    limit: Optional[int],
) -> tuple[int, Optional[int]]:
    if limit is not None and maximum is not None:
        raise ValueError("--limit cannot be combined with --max")
    if limit is not None:
        maximum = minimum + limit - 1
    if maximum is not None and maximum < minimum:
        raise ValueError("--max must be greater than or equal to --min")
    return minimum, maximum


def load_scraper_class():
    spec = importlib.util.spec_from_file_location(
        "mymobile_scraper",
        SCRAPER_PATH,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load scraper from {SCRAPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scraper_class = getattr(module, "MymobileScraper", None)
    if scraper_class is None:
        raise ImportError("MymobileScraper class not found")
    return scraper_class


def load_manifest(path: Path) -> List[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load manifest {path}: {exc}") from exc

    candidates = data.get("mobile_urls", [])
    urls: List[str] = []
    seen: set[str] = set()

    for entry in candidates:
        url = entry.get("url") if isinstance(entry, dict) else entry
        if not isinstance(url, str):
            continue
        if category_match(url) or product_match(url):
            if url not in seen:
                seen.add(url)
                urls.append(url)

    if not urls:
        raise ValueError(
            f"No MyMobile category/product URLs found in {path}"
        )
    return urls


class MymobileNavigator:
    BLOCKED_RESOURCE_TYPES = {"image", "font", "media"}

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
        self.navigation_timeout_ms = navigation_timeout_ms
        self.selector_timeout_ms = selector_timeout_ms
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.load_assets = load_assets
        self._playwright = None
        self.browser = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Install requirements and run "
                "'python -m playwright install chromium'."
            ) from exc

        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(
            headless=self.headless
        )
        return self

    def __exit__(self, *_):
        if self.browser:
            self.browser.close()
            self.browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def _pause(self) -> None:
        if self.delay_max:
            time.sleep(
                random.uniform(self.delay_min, self.delay_max)
            )

    def context(self):
        return self.browser.new_context(
            locale="en-PK",
            viewport={"width": 1366, "height": 900},
            service_workers="block",
        )

    def page(self, context):
        page = context.new_page()
        if not self.load_assets:
            page.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type in self.BLOCKED_RESOURCE_TYPES
                    else route.continue_()
                ),
            )
        return page

    def discover_category(
        self,
        page,
        category_url: str,
    ) -> tuple[List[str], List[str]]:
        response = page.goto(
            category_url,
            wait_until="domcontentloaded",
            timeout=self.navigation_timeout_ms,
        )
        if response is not None and response.status >= 400:
            raise RuntimeError(
                f"HTTP {response.status} for {category_url}"
            )

        page.wait_for_selector(
            'a[href*="/products/"]',
            timeout=self.selector_timeout_ms,
        )

        hrefs = page.eval_on_selector_all(
            'a[href*="/products/"]',
            "els => els.map(e => e.getAttribute('href'))",
        )

        product_urls: List[str] = []
        seen_products: set[str] = set()

        for href in hrefs:
            if not isinstance(href, str):
                continue
            candidate = urljoin(page.url, href).split("#", 1)[0]
            parsed = urlparse(candidate)
            candidate = parsed._replace(query="").geturl()

            if product_match(candidate) and candidate not in seen_products:
                seen_products.add(candidate)
                product_urls.append(candidate)

        # MyMobile category pages currently expose pagination with a visible
        # "Next" link. We also accept numbered page links while staying inside
        # the same /category/ path.
        pagination_hrefs = page.eval_on_selector_all(
            'a[href]',
            "els => els.map(e => ({href:e.getAttribute('href'), "
            "text:(e.innerText || '').trim()}))",
        )

        next_pages: List[str] = []
        seen_pages: set[str] = set()

        for item in pagination_hrefs:
            if not isinstance(item, dict):
                continue

            href = item.get("href")
            text = str(item.get("text") or "").strip().lower()

            if not isinstance(href, str):
                continue

            candidate = urljoin(page.url, href).split("#", 1)[0]
            parsed = urlparse(candidate)

            if parsed.query:
                continue

            if not category_match(candidate):
                continue

            # Only follow pagination-looking links. This prevents ordinary
            # category/brand navigation from becoming part of the crawl.
            looks_like_page = (
                text in {"next", "older", "next page", "›", "→"}
                or bool(re.search(r"/page/\d+/?$", parsed.path))
            )

            if looks_like_page and candidate not in seen_pages:
                seen_pages.add(candidate)
                next_pages.append(candidate)

        self._pause()

        if not product_urls:
            raise RuntimeError(
                f"No product links found on category page {category_url}"
            )

        return product_urls, next_pages

    def scrape_product(self, page, url: str) -> dict:
        if not product_match(url):
            raise ValueError(f"Not a MyMobile product URL: {url}")

        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self.navigation_timeout_ms,
        )
        if response is not None and response.status >= 400:
            raise RuntimeError(f"HTTP {response.status} for {url}")

        page.wait_for_selector(
            "h1",
            timeout=self.selector_timeout_ms,
        )

        if canonical_site(page.url) != "mymobile.pk":
            raise RuntimeError(
                f"Unexpected redirect from {url} to {page.url}"
            )

        scraper = load_scraper_class()(
            page.content(),
            source_url=url,
        )
        result = scraper.to_template()

        self._pause()

        if not result.get("MobileName"):
            raise RuntimeError(
                f"Scraper produced no MobileName for {url}"
            )

        return result


@dataclass
class Stats:
    started_at: str
    finished_at: Optional[str] = None
    range_min: int = 1
    range_max: Optional[int] = None
    manifest_entries: int = 0
    categories_visited: int = 0
    products_discovered: int = 0
    duplicate_products: int = 0
    selected_urls: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0


def crawl(
    seeds: List[str],
    output_dir: Path,
    args,
    minimum: int,
    maximum: Optional[int],
) -> int:
    stats = Stats(
        started_at=utc_now(),
        range_min=minimum,
        range_max=maximum,
        manifest_entries=len(seeds),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    failures = output_dir / "_failures.jsonl"
    summary = output_dir / "_crawl_summary.json"

    discovered: List[str] = []
    seen: set[str] = set()
    category_seen: set[str] = set()
    category_queue: List[str] = [
        url for url in seeds if category_match(url)
    ]
    direct_products: List[str] = [
        url for url in seeds if product_match(url)
    ]

    with MymobileNavigator(
        headless=not args.headed,
        navigation_timeout_ms=args.navigation_timeout_ms,
        selector_timeout_ms=args.selector_timeout_ms,
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        load_assets=args.load_assets,
    ) as nav:

        context = nav.context()
        try:
            listing_page = nav.page(context)

            # Discover products from all category seeds and their pagination.
            while category_queue:
                category_url = category_queue.pop(0)

                if category_url in category_seen:
                    continue
                category_seen.add(category_url)

                last_error: Optional[Exception] = None
                result: Optional[tuple[List[str], List[str]]] = None

                for attempt in range(args.retries + 1):
                    try:
                        LOG.info(
                            "CATEGORY %d: %s",
                            len(category_seen),
                            category_url,
                        )
                        result = nav.discover_category(
                            listing_page,
                            category_url,
                        )
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc
                        LOG.warning(
                            "Category attempt %d failed for %s: %s",
                            attempt + 1,
                            category_url,
                            exc,
                        )

                if result is None:
                    stats.failed += 1
                    with failures.open(
                        "a",
                        encoding="utf-8",
                    ) as handle:
                        handle.write(
                            json.dumps(
                                {
                                    "timestamp": utc_now(),
                                    "kind": "category",
                                    "url": category_url,
                                    "error": str(last_error),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                    continue

                stats.categories_visited += 1
                products, next_pages = result

                for product_url in products:
                    if product_url in seen:
                        stats.duplicate_products += 1
                        continue
                    seen.add(product_url)
                    discovered.append(product_url)

                for next_page in next_pages:
                    if next_page not in category_seen:
                        category_queue.append(next_page)

            # Direct product URLs in the manifest are also accepted. They are
            # useful as a fallback and make the navigator work if the manifest
            # is later regenerated into direct product entries.
            for product_url in direct_products:
                if product_url not in seen:
                    seen.add(product_url)
                    discovered.append(product_url)

            stats.products_discovered = len(discovered)

            selected = discovered[minimum - 1 : maximum]
            stats.selected_urls = len(selected)

            for position, url in enumerate(
                selected,
                start=minimum,
            ):
                target = output_dir / output_filename(url)

                if not args.force and valid_existing_output(target):
                    stats.skipped += 1
                    LOG.info(
                        "[%d%s] SKIP %s",
                        position,
                        f"/{maximum}" if maximum is not None else "",
                        target.name,
                    )
                    continue

                error: Optional[Exception] = None

                for attempt in range(args.retries + 1):
                    detail = None
                    try:
                        LOG.info(
                            "[%d%s] FETCH %s (attempt %d/%d)",
                            position,
                            f"/{maximum}" if maximum is not None else "",
                            url,
                            attempt + 1,
                            args.retries + 1,
                        )

                        detail = nav.page(context)
                        result = nav.scrape_product(detail, url)
                        atomic_write_json(target, result)
                        stats.succeeded += 1
                        error = None
                        break

                    except Exception as exc:
                        error = exc
                        LOG.warning(
                            "Product attempt %d failed for %s: %s",
                            attempt + 1,
                            url,
                            exc,
                        )
                    finally:
                        if detail is not None:
                            detail.close()

                if error is not None:
                    stats.failed += 1
                    with failures.open(
                        "a",
                        encoding="utf-8",
                    ) as handle:
                        handle.write(
                            json.dumps(
                                {
                                    "timestamp": utc_now(),
                                    "kind": "product",
                                    "url": url,
                                    "output_file": str(target),
                                    "attempts": args.retries + 1,
                                    "error": str(error),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
        finally:
            context.close()

    stats.finished_at = utc_now()
    atomic_write_json(summary, asdict(stats))

    LOG.info(
        "Summary: discovered=%d selected=%d saved=%d skipped=%d failed=%d",
        stats.products_discovered,
        stats.selected_urls,
        stats.succeeded,
        stats.skipped,
        stats.failed,
    )

    return 1 if stats.failed else 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Crawl MyMobile.pk category pages into normalized phone JSON."
    )
    p.add_argument(
        "url",
        nargs="?",
        help="Optional MyMobile category or product URL.",
    )
    p.add_argument(
        "--sitemap",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    p.add_argument(
        "--min",
        dest="minimum",
        type=positive_int,
        default=1,
    )
    p.add_argument(
        "--max",
        dest="maximum",
        type=positive_int,
    )
    p.add_argument(
        "--limit",
        type=positive_int,
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
    )
    p.add_argument(
        "--headed",
        action="store_true",
    )
    p.add_argument(
        "--force",
        action="store_true",
    )
    p.add_argument(
        "--retries",
        type=lambda value: max(0, int(value)),
        default=2,
    )
    p.add_argument(
        "--delay-min",
        type=nonnegative_float,
        default=2.0,
    )
    p.add_argument(
        "--delay-max",
        type=nonnegative_float,
        default=5.0,
    )
    p.add_argument(
        "--navigation-timeout-ms",
        type=positive_int,
        default=30_000,
    )
    p.add_argument(
        "--selector-timeout-ms",
        type=positive_int,
        default=15_000,
    )
    p.add_argument(
        "--load-assets",
        action="store_true",
    )
    p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.delay_max < args.delay_min:
        parser().error(
            "--delay-max must be greater than or equal to --delay-min"
        )

    try:
        minimum, maximum = resolve_range(
            args.minimum,
            args.maximum,
            args.limit,
        )
    except ValueError as exc:
        parser().error(str(exc))

    if args.url:
        if not (category_match(args.url) or product_match(args.url)):
            parser().error(
                "URL must be a MyMobile category or product URL"
            )
        seeds = [args.url]
    else:
        try:
            seeds = load_manifest(args.sitemap)
        except ValueError as exc:
            LOG.error("%s", exc)
            return 2

    if args.dry_run:
        categories = [url for url in seeds if category_match(url)]
        products = [url for url in seeds if product_match(url)]
        selected_products = products[minimum - 1 : maximum]

        print(
            json.dumps(
                {
                    "manifest": str(args.sitemap) if not args.url else args.url,
                    "categories": len(categories),
                    "direct_products": len(products),
                    "category_sample": categories[:5],
                    "direct_product_sample": products[:5],
                    "range_min": minimum,
                    "range_max": maximum,
                    "direct_products_selected": len(selected_products),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    return crawl(
        seeds,
        args.output_dir,
        args,
        minimum,
        maximum,
    )


if __name__ == "__main__":
    sys.exit(main())