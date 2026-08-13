"""
Cross-platform Playwright navigation and batch crawling for GSMArena.

This module keeps the original single-URL smoke-test interface while adding a
production manifest modes.  It runs unchanged on native Windows and Linux/WSL.

Single page (backward compatible):

    python backend/navigation_to_page/www.gsmarena.com.py \
        "https://www.gsmarena.com/xiaomi_redmi_note_14_4g_(global)-13616.php"

Inspect a manifest without opening a browser:

    python backend/navigation_to_page/www.gsmarena.com.py \
        --sitemap filestorage/sitemap_mobile/gsmarena.com.json --dry-run

Small resumable crawl (1-based, inclusive phone positions):

    python backend/navigation_to_page/www.gsmarena.com.py \
        --min 1 --max 5

Full resumable crawl:

    python backend/navigation_to_page/www.gsmarena.com.py --min 1

Catalog traversal matching the visible browser workflow:

    python backend/navigation_to_page/www.gsmarena.com.py \
        "https://www.gsmarena.com/xiaomi-phones-80.php" --min 1 --max 5 --headed

Outputs default to ``filestorage/mobiles/gsmarena.com/``.  Each successful
phone is written atomically using the repository's filename convention, e.g.
``gsmarena__xiaomi_redmi_note_14_4g_(global)-13616.php.json``. In catalog mode
the maker/listing page remains open while a second Playwright page visits and
scrapes each phone, then closes so control visibly returns to the listing.
Pagination is followed automatically. Existing valid files are skipped unless
``--force`` is supplied. Final failures are appended to ``_failures.jsonl`` and
every run writes ``_crawl_summary.json``.

When neither a positional URL nor ``--sitemap`` is supplied, the script uses
``filestorage/sitemap_mobile/gsmarena.com.json`` automatically. ``--min`` and
``--max`` therefore form the complete normal Windows batch interface. Ranges
are 1-based and inclusive; for example, ``--min 101 --max 200`` owns exactly
the stable phone positions 101 through 200. ``--limit`` remains as a deprecated
compatibility alias for a range length.
"""

from __future__ import annotations

import argparse
from collections import deque
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

log = logging.getLogger("gsmarena.navigator")

DEFAULT_MANIFEST = "filestorage/sitemap_mobile/gsmarena.com.json"
DEFAULT_OUTPUT_DIR = "filestorage/mobiles/gsmarena.com"
DEFAULT_WAIT_SELECTOR = "#specs-list"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / DEFAULT_MANIFEST
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / DEFAULT_OUTPUT_DIR

_SCRAPER_PATH = (
    Path(__file__).resolve().parent.parent / "scrapers" / "www.gsmarena.com.py"
)
_SCRAPER_CLASS: Optional[type] = None

GSMARENA_PRODUCT_FILE_RE = re.compile(
    r"^(?P<slug>[a-z0-9][a-z0-9_()+.,%'-]*)-(?P<product_id>[0-9]+)\.php$",
    re.IGNORECASE,
)
GSMARENA_NON_PRODUCT_MARKER_RE = re.compile(
    r"-(?:phones?|reviews?|pictures?|opinions?|prices?|videos?|related|compare|news)-",
    re.IGNORECASE,
)
GSMARENA_CATALOG_FILE_RE = re.compile(
    r"^(?P<maker_slug>[a-z0-9][a-z0-9_()+.,%'-]*)-phones-"
    r"(?P<maker_id>[0-9]+)\.php$",
    re.IGNORECASE,
)
GSMARENA_CATALOG_PAGE_FILE_RE = re.compile(
    r"^(?P<maker_slug>[a-z0-9][a-z0-9_()+.,%'-]*)-phones-f-"
    r"(?P<maker_id>[0-9]+)-(?P<variant>.+)-p(?P<page>[0-9]+)\.php$",
    re.IGNORECASE,
)
WINDOWS_INVALID_FILENAME_RE = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_site(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    return re.sub(r"^www\.", "", host)


def gsmarena_product_match(url: str) -> Optional[re.Match[str]]:
    parsed = urlparse(url)
    if canonical_site(url) != "gsmarena.com" or parsed.query or parsed.fragment:
        return None

    filename = unquote(Path(parsed.path).name)
    match = GSMARENA_PRODUCT_FILE_RE.fullmatch(filename)
    if match is None:
        return None
    if "_" not in match.group("slug"):
        return None
    if GSMARENA_NON_PRODUCT_MARKER_RE.search(filename):
        return None
    return match


def gsmarena_catalog_match(url: str) -> Optional[re.Match[str]]:
    """Match a canonical maker landing page such as xiaomi-phones-80.php."""
    parsed = urlparse(url)
    if canonical_site(url) != "gsmarena.com" or parsed.query or parsed.fragment:
        return None
    return GSMARENA_CATALOG_FILE_RE.fullmatch(unquote(Path(parsed.path).name))


def gsmarena_catalog_page_match(url: str) -> Optional[re.Match[str]]:
    """Match either a canonical maker page or one of its pagination pages."""
    base_match = gsmarena_catalog_match(url)
    if base_match is not None:
        return base_match
    parsed = urlparse(url)
    if canonical_site(url) != "gsmarena.com" or parsed.query or parsed.fragment:
        return None
    return GSMARENA_CATALOG_PAGE_FILE_RE.fullmatch(
        unquote(Path(parsed.path).name)
    )


def catalog_identity(url: str) -> Optional[tuple[str, int]]:
    match = gsmarena_catalog_page_match(url)
    if match is None:
        return None
    return match.group("maker_slug").lower(), int(match.group("maker_id"))


def output_filename(url: str) -> str:
    """Create the same legal filename on Linux, WSL, and Windows."""
    filename = unquote(Path(urlparse(url).path).name)
    filename = WINDOWS_INVALID_FILENAME_RE.sub("_", filename).rstrip(". ")
    if not filename:
        raise ValueError(f"Could not derive an output filename from {url!r}")
    return f"gsmarena__{filename}.json"


def load_scraper_class() -> type:
    global _SCRAPER_CLASS
    if _SCRAPER_CLASS is not None:
        return _SCRAPER_CLASS
    if not _SCRAPER_PATH.is_file():
        raise FileNotFoundError(f"GSMArena scraper not found: {_SCRAPER_PATH}")

    spec = importlib.util.spec_from_file_location("gsmarena_scraper", _SCRAPER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load scraper module from {_SCRAPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scraper_class = getattr(module, "GsmarenaScraper", None)
    if scraper_class is None:
        raise ImportError(f"GsmarenaScraper class not found in {_SCRAPER_PATH}")
    _SCRAPER_CLASS = scraper_class
    return scraper_class


def import_playwright() -> tuple[Any, type[BaseException], type[BaseException]]:
    """Delay the Playwright import so ``--dry-run`` needs no browser runtime."""
    try:
        from playwright.sync_api import Error, TimeoutError, sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed for this Python interpreter. Run "
            "'python -m pip install -r requirements.txt' and then "
            "'python -m playwright install chromium'."
        ) from exc
    return sync_playwright, Error, TimeoutError


def parse_proxy(value: str) -> dict:
    candidate = value.strip()
    if not candidate:
        raise ValueError("Proxy value cannot be empty")
    if "://" not in candidate:
        candidate = f"http://{candidate}"

    parsed = urlparse(candidate)
    if not parsed.hostname or not parsed.port:
        raise ValueError(
            f"Invalid proxy {value!r}; expected host:port or scheme://host:port"
        )
    proxy: dict[str, str] = {
        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    }
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy


def load_proxies(values: Sequence[str], proxy_file: Optional[Path]) -> List[dict]:
    raw_values = list(values)
    if proxy_file is not None:
        try:
            for line in proxy_file.read_text(encoding="utf-8-sig").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    raw_values.append(stripped)
        except OSError as exc:
            raise ValueError(f"Could not read proxy file {proxy_file}: {exc}") from exc
    return [parse_proxy(value) for value in raw_values]


class GsmarenaEvasion:
    """Request identity, optional user-supplied proxy rotation, and throttling."""

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 "
        "Safari/537.36 Edg/151.0.0.0",
    ]

    def __init__(
        self,
        proxies: Optional[Sequence[dict]] = None,
        minimum_delay: float = 2.0,
        maximum_delay: float = 5.0,
    ) -> None:
        if minimum_delay < 0 or maximum_delay < minimum_delay:
            raise ValueError("Delay range must satisfy 0 <= minimum <= maximum")
        self.proxies = list(proxies or [])
        self.minimum_delay = minimum_delay
        self.maximum_delay = maximum_delay

    def random_user_agent(self) -> str:
        return random.choice(self.USER_AGENTS)

    def random_proxy(self) -> Optional[dict]:
        return random.choice(self.proxies) if self.proxies else None

    def polite_delay(self) -> None:
        if self.maximum_delay:
            time.sleep(random.uniform(self.minimum_delay, self.maximum_delay))


class GsmarenaNavigator:
    """Own a Playwright browser and scrape GSMArena specification pages."""

    BLOCKED_RESOURCE_TYPES = {"font", "image", "media"}

    def __init__(
        self,
        evasion: Optional[GsmarenaEvasion] = None,
        headless: bool = True,
        navigation_timeout_ms: int = 30_000,
        selector_timeout_ms: int = 15_000,
        block_assets: bool = True,
    ) -> None:
        self.evasion = evasion or GsmarenaEvasion()
        self.headless = headless
        self.navigation_timeout_ms = navigation_timeout_ms
        self.selector_timeout_ms = selector_timeout_ms
        self.block_assets = block_assets
        self._playwright_manager: Any = None
        self._browser: Any = None
        self._playwright_error: type[BaseException] = Exception
        self._playwright_timeout: type[BaseException] = Exception

    def start(self) -> "GsmarenaNavigator":
        if self._playwright_manager is not None:
            return self
        sync_playwright, error_type, timeout_type = import_playwright()
        self._playwright_error = error_type
        self._playwright_timeout = timeout_type
        self._playwright_manager = sync_playwright().start()
        try:
            self._launch_browser()
        except Exception:
            self._playwright_manager.stop()
            self._playwright_manager = None
            raise
        return self

    def _launch_browser(self) -> None:
        if self._playwright_manager is None:
            raise RuntimeError("Playwright has not been started")
        self._browser = self._playwright_manager.chromium.launch(
            headless=self.headless
        )

    def restart_browser(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
        self._browser = None
        self._launch_browser()

    def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            finally:
                self._browser = None
        if self._playwright_manager is not None:
            try:
                self._playwright_manager.stop()
            finally:
                self._playwright_manager = None

    def __enter__(self) -> "GsmarenaNavigator":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def new_context(self) -> Any:
        """Create an isolated browser context for one direct request or maker."""
        if self._browser is None:
            raise RuntimeError("Browser is not running")
        context_options: dict[str, Any] = {
            "user_agent": self.evasion.random_user_agent(),
            "locale": "en-US",
            "viewport": {"width": 1366, "height": 900},
            "service_workers": "block",
        }
        proxy = self.evasion.random_proxy()
        if proxy:
            context_options["proxy"] = proxy
        return self._browser.new_context(**context_options)

    # Backward-compatible private name used by the first implementation.
    def _new_context(self) -> Any:
        return self.new_context()

    @classmethod
    def _route_request(cls, route: Any) -> None:
        if route.request.resource_type in cls.BLOCKED_RESOURCE_TYPES:
            route.abort()
        else:
            route.continue_()

    def new_page(self, context: Any) -> Any:
        page = context.new_page()
        if self.block_assets:
            page.route("**/*", self._route_request)
        return page

    def scrape_product_on_page(
        self,
        page: Any,
        url: str,
        wait_selector: str = DEFAULT_WAIT_SELECTOR,
    ) -> dict:
        """Navigate an existing page to one phone and invoke the scraper.

        Catalog mode uses this method on a temporary detail page while the
        maker listing remains open in a different page of the same context.
        """
        if gsmarena_product_match(url) is None:
            raise ValueError(f"Not a recognized GSMArena product URL: {url}")

        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.navigation_timeout_ms,
            )
            if response is not None and response.status >= 400:
                raise RuntimeError(f"HTTP {response.status} while loading {url}")
            page.wait_for_selector(wait_selector, timeout=self.selector_timeout_ms)
            final_url = page.url
            if canonical_site(final_url) != "gsmarena.com":
                raise RuntimeError(f"Unexpected redirect from {url} to {final_url}")
            html = page.content()
        finally:
            self.evasion.polite_delay()

        scraper_class = load_scraper_class()
        scraper = scraper_class(html, source_url=url)
        raw = scraper.scrape()
        template = scraper.to_template(raw)
        if not template.get("MobileName"):
            raise RuntimeError(f"Scraper produced no MobileName for {url}")
        return {"raw": raw, "template": template}

    def discover_catalog_page(
        self,
        page: Any,
        url: str,
        expected_identity: tuple[str, int],
    ) -> dict:
        """Load one maker/pagination page and extract phone and page links."""
        actual_identity = catalog_identity(url)
        if actual_identity != expected_identity:
            raise ValueError(
                f"Catalog page {url!r} does not belong to maker {expected_identity}"
            )

        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.navigation_timeout_ms,
            )
            if response is not None and response.status >= 400:
                raise RuntimeError(f"HTTP {response.status} while loading {url}")
            page.wait_for_selector(
                ".makers a[href]",
                timeout=self.selector_timeout_ms,
            )
            if canonical_site(page.url) != "gsmarena.com":
                raise RuntimeError(f"Unexpected redirect from {url} to {page.url}")

            product_hrefs = page.eval_on_selector_all(
                ".makers a[href]",
                "elements => elements.map(element => element.getAttribute('href'))",
            )
            pagination_hrefs = page.eval_on_selector_all(
                ".nav-pages a[href], a.pages-next[href], a.pages-prev[href]",
                "elements => elements.map(element => element.getAttribute('href'))",
            )
        finally:
            self.evasion.polite_delay()

        products: List[str] = []
        product_seen: set[str] = set()
        for href in product_hrefs:
            if not isinstance(href, str):
                continue
            candidate = urljoin(page.url, href)
            if candidate not in product_seen and gsmarena_product_match(candidate):
                product_seen.add(candidate)
                products.append(candidate)

        pagination: List[str] = []
        page_seen: set[str] = set()
        for href in pagination_hrefs:
            if not isinstance(href, str):
                continue
            candidate = urljoin(page.url, href)
            if (
                candidate != url
                and candidate not in page_seen
                and catalog_identity(candidate) == expected_identity
            ):
                page_seen.add(candidate)
                pagination.append(candidate)

        if not products:
            raise RuntimeError(f"No phone links found on catalog page {url}")
        return {
            "url": url,
            "final_url": page.url,
            "product_urls": products,
            "pagination_urls": pagination,
        }

    def fetch_product(
        self,
        url: str,
        wait_selector: str = DEFAULT_WAIT_SELECTOR,
    ) -> dict:
        if gsmarena_product_match(url) is None:
            raise ValueError(f"Not a recognized GSMArena product URL: {url}")

        context = self.new_context()
        page = self.new_page(context)

        try:
            return self.scrape_product_on_page(page, url, wait_selector)
        finally:
            context.close()

    def fetch_many(
        self,
        urls: Sequence[str],
        wait_selector: str = DEFAULT_WAIT_SELECTOR,
    ) -> List[dict]:
        results: List[dict] = []
        for url in urls:
            try:
                results.append(self.fetch_product(url, wait_selector))
            except Exception as exc:
                results.append({"url": url, "error": str(exc)})
        return results


def iter_tree_urls(tree: dict) -> Iterator[str]:
    stack = [tree]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        url = node.get("url")
        if isinstance(url, str):
            yield url
        children = node.get("children", [])
        if isinstance(children, list):
            stack.extend(reversed(children))


def iter_manifest_records(data: Any) -> Iterator[str]:
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict) and isinstance(data.get("mobile_urls"), list):
        records = data["mobile_urls"]
    elif isinstance(data, dict) and isinstance(data.get("tree"), dict):
        yield from iter_tree_urls(data["tree"])
        return
    else:
        raise ValueError(
            "Manifest must be a URL list, contain a 'mobile_urls' list, "
            "or contain a sitemap 'tree' object"
        )

    for record in records:
        if isinstance(record, str):
            yield record
        elif isinstance(record, dict) and isinstance(record.get("url"), str):
            yield record["url"]


def iter_catalog_records(data: Any) -> Iterator[str]:
    """Read maker landing pages from the explicit list or filtered tree."""
    if isinstance(data, dict) and isinstance(data.get("catalog_urls"), list):
        records = data["catalog_urls"]
        for record in records:
            if isinstance(record, str):
                yield record
            elif isinstance(record, dict) and isinstance(record.get("url"), str):
                yield record["url"]
        return

    if isinstance(data, dict) and isinstance(data.get("tree"), dict):
        for url in iter_tree_urls(data["tree"]):
            if gsmarena_catalog_match(url) is not None:
                yield url


@dataclass(frozen=True)
class CatalogSeed:
    url: str
    maker_slug: str
    maker_id: int

    @classmethod
    def from_url(cls, url: str) -> "CatalogSeed":
        match = gsmarena_catalog_match(url)
        if match is None:
            raise ValueError(f"Not a canonical GSMArena maker page: {url}")
        return cls(
            url=url,
            maker_slug=match.group("maker_slug").lower(),
            maker_id=int(match.group("maker_id")),
        )


@dataclass
class ManifestSelection:
    path: str
    catalog_records_seen: int
    catalog_duplicate_records: int
    rejected_non_catalogs: int
    catalogs: List[CatalogSeed]
    records_seen: int
    duplicate_records: int
    rejected_non_products: int
    product_urls: List[str]


def load_manifest(path: Path) -> ManifestSelection:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ValueError(f"Could not read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Manifest is not valid JSON: {path}: {exc}") from exc

    catalog_seen: set[str] = set()
    catalogs: List[CatalogSeed] = []
    catalog_records_seen = 0
    catalog_duplicates = 0
    rejected_catalogs = 0
    for url in iter_catalog_records(data):
        catalog_records_seen += 1
        if url in catalog_seen:
            catalog_duplicates += 1
            continue
        catalog_seen.add(url)
        match = gsmarena_catalog_match(url)
        if match is None:
            rejected_catalogs += 1
            continue
        catalogs.append(CatalogSeed.from_url(url))

    seen: set[str] = set()
    products: List[str] = []
    records_seen = 0
    duplicates = 0
    rejected = 0

    for url in iter_manifest_records(data):
        records_seen += 1
        if url in seen:
            duplicates += 1
            continue
        seen.add(url)
        if gsmarena_product_match(url) is None:
            rejected += 1
            continue
        products.append(url)

    return ManifestSelection(
        path=str(path),
        catalog_records_seen=catalog_records_seen,
        catalog_duplicate_records=catalog_duplicates,
        rejected_non_catalogs=rejected_catalogs,
        catalogs=catalogs,
        records_seen=records_seen,
        duplicate_records=duplicates,
        rejected_non_products=rejected,
        product_urls=products,
    )


def atomic_write_json(path: Path, payload: Any) -> None:
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
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and bool(payload.get("MobileName"))


def append_json_line(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


@dataclass
class CrawlStats:
    manifest: str
    output_dir: str
    started_at: str
    crawl_mode: str = "direct"
    finished_at: Optional[str] = None
    eligible_catalogs: int = 0
    selected_catalogs: int = 0
    catalog_pages_visited: int = 0
    catalog_pages_failed: int = 0
    products_discovered: int = 0
    duplicate_products_discovered: int = 0
    manifest_records_seen: int = 0
    manifest_duplicates: int = 0
    manifest_rejected_non_products: int = 0
    eligible_product_urls: int = 0
    range_min: int = 1
    range_max: Optional[int] = None
    range_skipped_before_min: int = 0
    selected_urls: int = 0
    already_complete: int = 0
    succeeded: int = 0
    failed: int = 0
    interrupted: bool = False


def retry_backoff(attempt_number: int) -> None:
    delay = min(30.0, (2.0**attempt_number) + random.uniform(0.0, 1.0))
    time.sleep(delay)


def resolve_phone_range(
    minimum: int,
    maximum: Optional[int],
    limit: Optional[int] = None,
) -> tuple[int, Optional[int]]:
    """Resolve the public 1-based inclusive phone range.

    ``--limit`` is retained for old commands. It represents a count beginning
    at ``minimum`` and cannot be combined with an explicit maximum.
    """
    if minimum < 1:
        raise ValueError("minimum phone position must be at least 1")
    if maximum is not None and maximum < minimum:
        raise ValueError("maximum phone position must be >= minimum")
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if maximum is not None:
            raise ValueError("--limit cannot be combined with --max")
        maximum = minimum + limit - 1
    return minimum, maximum


def select_phone_range(
    urls: Sequence[str],
    minimum: int,
    maximum: Optional[int],
) -> List[str]:
    """Select 1-based inclusive positions from an ordered URL sequence."""
    start = minimum - 1
    return list(urls[start:maximum])


def range_label(minimum: int, maximum: Optional[int]) -> str:
    return f"{minimum}-{maximum if maximum is not None else 'end'}"


def crawl_manifest(
    selection: ManifestSelection,
    output_dir: Path,
    *,
    minimum: int,
    maximum: Optional[int],
    force: bool,
    retries: int,
    navigator: GsmarenaNavigator,
) -> int:
    selected = select_phone_range(selection.product_urls, minimum, maximum)
    failures_path = output_dir / "_failures.jsonl"
    summary_path = output_dir / "_crawl_summary.json"
    stats = CrawlStats(
        manifest=selection.path,
        output_dir=str(output_dir),
        started_at=utc_now(),
        manifest_records_seen=selection.records_seen,
        manifest_duplicates=selection.duplicate_records,
        manifest_rejected_non_products=selection.rejected_non_products,
        eligible_product_urls=len(selection.product_urls),
        range_min=minimum,
        range_max=maximum,
        selected_urls=len(selected),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    log.info(
        "Manifest contains %d eligible product URL(s); range %s selected %d",
        len(selection.product_urls),
        range_label(minimum, maximum),
        len(selected),
    )

    try:
        with navigator:
            for index, url in enumerate(selected, start=minimum):
                output_path = output_dir / output_filename(url)
                if not force and valid_existing_output(output_path):
                    stats.already_complete += 1
                    log.info(
                        "[phone %d%s] SKIP %s",
                        index,
                        f"/{maximum}" if maximum is not None else "",
                        output_path.name,
                    )
                    continue

                maximum_attempts = retries + 1
                last_error: Optional[BaseException] = None
                for attempt in range(1, maximum_attempts + 1):
                    try:
                        log.info(
                            "[phone %d%s] FETCH %s (attempt %d/%d)",
                            index,
                            f"/{maximum}" if maximum is not None else "",
                            url,
                            attempt,
                            maximum_attempts,
                        )
                        result = navigator.fetch_product(url)
                        atomic_write_json(output_path, result["template"])
                        stats.succeeded += 1
                        log.info("[phone %d] SAVED %s", index, output_path)
                        last_error = None
                        break
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:
                        last_error = exc
                        log.warning(
                            "[phone %d] attempt %d failed for %s: %s",
                            index,
                            attempt,
                            url,
                            exc,
                        )
                        if attempt < maximum_attempts:
                            try:
                                navigator.restart_browser()
                            except Exception as restart_exc:
                                log.warning("Browser restart failed: %s", restart_exc)
                            retry_backoff(attempt)

                if last_error is not None:
                    stats.failed += 1
                    append_json_line(
                        failures_path,
                        {
                            "timestamp": utc_now(),
                            "url": url,
                            "output_file": str(output_path),
                            "attempts": maximum_attempts,
                            "error_type": type(last_error).__name__,
                            "error": str(last_error),
                        },
                    )
    except KeyboardInterrupt:
        stats.interrupted = True
        log.warning("Interrupted; completed files are preserved for resume")
    finally:
        stats.finished_at = utc_now()
        atomic_write_json(summary_path, asdict(stats))
        log.info(
            "Summary: saved=%d, skipped=%d, failed=%d, interrupted=%s",
            stats.succeeded,
            stats.already_complete,
            stats.failed,
            stats.interrupted,
        )

    if stats.interrupted:
        return 130
    return 1 if stats.failed else 0


def select_catalogs(
    catalogs: Sequence[CatalogSeed],
    maker_filters: Sequence[str],
    catalog_limit: Optional[int],
) -> List[CatalogSeed]:
    selected = list(catalogs)
    if maker_filters:
        normalized = {
            value.strip().lower().replace(" ", "_")
            for value in maker_filters
            if value.strip()
        }
        selected = [
            catalog
            for catalog in selected
            if catalog.maker_slug in normalized or str(catalog.maker_id) in normalized
        ]
    if catalog_limit is not None:
        selected = selected[:catalog_limit]
    return selected


def safe_close(resource: Any) -> None:
    if resource is None:
        return
    try:
        resource.close()
    except Exception:
        pass


def crawl_catalogs(
    selection: ManifestSelection,
    catalogs: Sequence[CatalogSeed],
    output_dir: Path,
    *,
    minimum: int,
    maximum: Optional[int],
    force: bool,
    retries: int,
    navigator: GsmarenaNavigator,
) -> int:
    """Traverse maker pages, their pagination, and every phone card.

    A listing page remains open for the whole maker. Each product is opened in
    a second page, scraped, and closed before focus returns to the listing.
    Existing valid JSON files provide resumability.
    """
    failures_path = output_dir / "_failures.jsonl"
    summary_path = output_dir / "_crawl_summary.json"
    discovery_path = output_dir / "_catalog_discovery.json"
    coverage_path = output_dir / "_catalog_coverage.json"
    stats = CrawlStats(
        manifest=selection.path,
        output_dir=str(output_dir),
        started_at=utc_now(),
        crawl_mode="catalog",
        eligible_catalogs=len(selection.catalogs),
        selected_catalogs=len(catalogs),
        manifest_records_seen=selection.records_seen,
        manifest_duplicates=selection.duplicate_records,
        manifest_rejected_non_products=selection.rejected_non_products,
        eligible_product_urls=len(selection.product_urls),
        range_min=minimum,
        range_max=maximum,
    )
    discovery_state: dict[str, Any] = {
        "version": 1,
        "manifest": selection.path,
        "started_at": stats.started_at,
        "updated_at": stats.started_at,
        "catalogs": {},
    }
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info(
        "Catalog mode: selected %d of %d maker landing page(s); phone range=%s",
        len(catalogs),
        len(selection.catalogs),
        range_label(minimum, maximum),
    )

    seen_products: set[str] = set()
    stop_requested = False

    try:
        with navigator:
            for catalog_index, catalog in enumerate(catalogs, start=1):
                if stop_requested:
                    break

                identity = (catalog.maker_slug, catalog.maker_id)
                queue = deque([catalog.url])
                queued_pages = {catalog.url}
                visited_pages: set[str] = set()
                catalog_state: dict[str, Any] = {
                    "maker_slug": catalog.maker_slug,
                    "maker_id": catalog.maker_id,
                    "landing_url": catalog.url,
                    "pages": {},
                }
                discovery_state["catalogs"][catalog.url] = catalog_state

                context = None
                listing_page = None
                try:
                    context = navigator.new_context()
                    listing_page = navigator.new_page(context)

                    while queue and not stop_requested:
                        page_url = queue.popleft()
                        if page_url in visited_pages:
                            continue

                        discovery: Optional[dict] = None
                        last_page_error: Optional[BaseException] = None
                        maximum_attempts = retries + 1
                        for attempt in range(1, maximum_attempts + 1):
                            try:
                                log.info(
                                    "[catalog %d/%d] LAND %s (attempt %d/%d)",
                                    catalog_index,
                                    len(catalogs),
                                    page_url,
                                    attempt,
                                    maximum_attempts,
                                )
                                listing_page.bring_to_front()
                                discovery = navigator.discover_catalog_page(
                                    listing_page,
                                    page_url,
                                    identity,
                                )
                                last_page_error = None
                                break
                            except KeyboardInterrupt:
                                raise
                            except Exception as exc:
                                last_page_error = exc
                                log.warning(
                                    "Catalog attempt %d failed for %s: %s",
                                    attempt,
                                    page_url,
                                    exc,
                                )
                                if attempt < maximum_attempts:
                                    retry_backoff(attempt)

                        visited_pages.add(page_url)
                        if discovery is None:
                            stats.catalog_pages_failed += 1
                            append_json_line(
                                failures_path,
                                {
                                    "timestamp": utc_now(),
                                    "kind": "catalog_page",
                                    "url": page_url,
                                    "maker_slug": catalog.maker_slug,
                                    "maker_id": catalog.maker_id,
                                    "attempts": maximum_attempts,
                                    "error_type": type(last_page_error).__name__,
                                    "error": str(last_page_error),
                                },
                            )
                            continue

                        stats.catalog_pages_visited += 1
                        catalog_state["pages"][page_url] = {
                            "final_url": discovery["final_url"],
                            "product_count": len(discovery["product_urls"]),
                            "product_urls": discovery["product_urls"],
                            "pagination_urls": discovery["pagination_urls"],
                            "visited_at": utc_now(),
                        }
                        discovery_state["updated_at"] = utc_now()
                        atomic_write_json(discovery_path, discovery_state)

                        for next_page in discovery["pagination_urls"]:
                            if next_page not in visited_pages and next_page not in queued_pages:
                                queued_pages.add(next_page)
                                queue.append(next_page)

                        for product_url in discovery["product_urls"]:
                            if product_url in seen_products:
                                stats.duplicate_products_discovered += 1
                                continue

                            product_position = len(seen_products) + 1
                            if maximum is not None and product_position > maximum:
                                stop_requested = True
                                break

                            seen_products.add(product_url)
                            stats.products_discovered += 1
                            if product_position < minimum:
                                stats.range_skipped_before_min += 1
                                log.debug(
                                    "[phone %d] before requested range; discovery only",
                                    product_position,
                                )
                                continue

                            stats.selected_urls += 1
                            output_path = output_dir / output_filename(product_url)
                            at_range_end = (
                                maximum is not None and product_position >= maximum
                            )

                            if not force and valid_existing_output(output_path):
                                stats.already_complete += 1
                                log.info(
                                    "[phone %d%s] SKIP %s",
                                    product_position,
                                    f"/{maximum}" if maximum is not None else "",
                                    output_path.name,
                                )
                                if at_range_end:
                                    stop_requested = True
                                    break
                                continue

                            last_product_error: Optional[BaseException] = None
                            for attempt in range(1, maximum_attempts + 1):
                                detail_page = None
                                try:
                                    log.info(
                                        "[phone %d%s] OPEN %s (attempt %d/%d)",
                                        product_position,
                                        f"/{maximum}" if maximum is not None else "",
                                        product_url,
                                        attempt,
                                        maximum_attempts,
                                    )
                                    detail_page = navigator.new_page(context)
                                    detail_page.bring_to_front()
                                    result = navigator.scrape_product_on_page(
                                        detail_page,
                                        product_url,
                                    )
                                    atomic_write_json(output_path, result["template"])
                                    stats.succeeded += 1
                                    last_product_error = None
                                    log.info("SAVED %s", output_path)
                                    break
                                except KeyboardInterrupt:
                                    raise
                                except Exception as exc:
                                    last_product_error = exc
                                    log.warning(
                                        "Product attempt %d failed for %s: %s",
                                        attempt,
                                        product_url,
                                        exc,
                                    )
                                    if attempt < maximum_attempts:
                                        retry_backoff(attempt)
                                finally:
                                    safe_close(detail_page)
                                    try:
                                        listing_page.bring_to_front()
                                    except Exception:
                                        pass

                            if last_product_error is not None:
                                stats.failed += 1
                                append_json_line(
                                    failures_path,
                                    {
                                        "timestamp": utc_now(),
                                        "kind": "product",
                                        "url": product_url,
                                        "catalog_page": page_url,
                                        "output_file": str(output_path),
                                        "attempts": maximum_attempts,
                                        "error_type": type(last_product_error).__name__,
                                        "error": str(last_product_error),
                                    },
                                )

                            if at_range_end:
                                stop_requested = True
                                break
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    stats.catalog_pages_failed += 1
                    log.exception(
                        "Unexpected maker-session failure for %s: %s",
                        catalog.url,
                        exc,
                    )
                    append_json_line(
                        failures_path,
                        {
                            "timestamp": utc_now(),
                            "kind": "catalog_session",
                            "url": catalog.url,
                            "maker_slug": catalog.maker_slug,
                            "maker_id": catalog.maker_id,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                finally:
                    safe_close(context)
    except KeyboardInterrupt:
        stats.interrupted = True
        log.warning("Interrupted; completed phone files are preserved for resume")
    except Exception as exc:
        stats.catalog_pages_failed += 1
        log.exception("Catalog crawler stopped unexpectedly: %s", exc)
        append_json_line(
            failures_path,
            {
                "timestamp": utc_now(),
                "kind": "catalog_crawler",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
    finally:
        stats.finished_at = utc_now()
        discovery_state["updated_at"] = stats.finished_at
        atomic_write_json(discovery_path, discovery_state)
        direct_products = set(selection.product_urls)
        discovered_products = set(seen_products)
        overlap = direct_products & discovered_products
        complete_catalog_scan = (
            maximum is None
            and len(catalogs) == len(selection.catalogs)
            and not stats.interrupted
            and stats.catalog_pages_failed == 0
        )
        atomic_write_json(
            coverage_path,
            {
                "manifest": selection.path,
                "generated_at": stats.finished_at,
                "complete_catalog_scan": complete_catalog_scan,
                "catalog_products_discovered": len(discovered_products),
                "direct_manifest_products": len(direct_products),
                "overlap_count": len(overlap),
                "catalog_only_count": len(discovered_products - direct_products),
                "direct_only_count": len(direct_products - discovered_products),
                "catalog_only_urls": sorted(discovered_products - direct_products),
                "direct_only_urls": sorted(direct_products - discovered_products),
                "note": (
                    "Counts are final only when complete_catalog_scan is true; "
                    "otherwise limits, maker selection, interruption, or failed "
                    "catalog pages make this a partial comparison."
                ),
            },
        )
        atomic_write_json(summary_path, asdict(stats))
        log.info(
            "Catalog summary: pages=%d, discovered=%d, saved=%d, skipped=%d, "
            "failed=%d, interrupted=%s",
            stats.catalog_pages_visited,
            stats.products_discovered,
            stats.succeeded,
            stats.already_complete,
            stats.failed + stats.catalog_pages_failed,
            stats.interrupted,
        )

    if stats.interrupted:
        return 130
    return 1 if stats.failed or stats.catalog_pages_failed else 0


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Navigate and scrape GSMArena product specification pages."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="One GSMArena product URL, or one maker page for catalog traversal.",
    )
    parser.add_argument(
        "--sitemap",
        type=Path,
        help=(
            "Filtered manifest to crawl. When URL and --sitemap are omitted, "
            f"the default is {DEFAULT_MANIFEST}."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Per-phone output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--crawl-mode",
        choices=["auto", "catalog", "direct"],
        default="auto",
        help="'auto' prefers maker-catalog traversal and falls back to direct URLs.",
    )
    parser.add_argument(
        "--maker",
        action="append",
        default=[],
        help="Catalog mode: select a maker slug/name or numeric id; repeatable.",
    )
    parser.add_argument(
        "--catalog-limit",
        type=positive_int,
        help="Catalog mode: use only the first N selected maker pages.",
    )
    parser.add_argument(
        "--min",
        "--minimum",
        dest="min_phone",
        type=positive_int,
        default=1,
        metavar="PHONE",
        help="First phone position to process, 1-based and inclusive (default: 1).",
    )
    parser.add_argument(
        "--max",
        "--maximum",
        dest="max_phone",
        type=positive_int,
        metavar="PHONE",
        help="Last phone position to process, 1-based and inclusive (default: end).",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        help=(
            "Deprecated compatibility option: process N phones beginning at "
            "--min. Cannot be combined with --max."
        ),
    )
    parser.add_argument(
        "--retries",
        type=non_negative_int,
        default=2,
        help="Retries after the first attempt for each URL (default: 2).",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite valid outputs.")
    parser.add_argument("--headed", action="store_true", help="Show the browser UI.")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw scraper output in single-URL mode.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and summarize the manifest without opening a browser.",
    )
    parser.add_argument(
        "--sample",
        type=positive_int,
        default=5,
        help="Number of manifest URLs to print in dry-run mode.",
    )
    parser.add_argument(
        "--delay-min",
        type=non_negative_float,
        default=2.0,
        help="Minimum delay after each request in seconds.",
    )
    parser.add_argument(
        "--delay-max",
        type=non_negative_float,
        default=5.0,
        help="Maximum delay after each request in seconds.",
    )
    parser.add_argument(
        "--navigation-timeout-ms", type=positive_int, default=30_000
    )
    parser.add_argument("--selector-timeout-ms", type=positive_int, default=15_000)
    parser.add_argument(
        "--load-assets",
        action="store_true",
        help="Load images/fonts/media instead of blocking them.",
    )
    parser.add_argument(
        "--proxy",
        action="append",
        default=[],
        help="Optional proxy URL; repeat to rotate user-supplied proxies.",
    )
    parser.add_argument(
        "--proxy-file",
        type=Path,
        help="Optional file containing one proxy per line.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    return parser


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def resolve_crawl_mode(selection: ManifestSelection, requested: str) -> str:
    if requested == "auto":
        return "catalog" if selection.catalogs else "direct"
    return requested


def manifest_dry_run(
    selection: ManifestSelection,
    *,
    requested_mode: str,
    maker_filters: Sequence[str],
    catalog_limit: Optional[int],
    minimum: int,
    maximum: Optional[int],
    sample: int,
) -> None:
    resolved_mode = resolve_crawl_mode(selection, requested_mode)
    selected_catalogs = select_catalogs(
        selection.catalogs,
        maker_filters,
        catalog_limit,
    )
    selected_products = select_phone_range(
        selection.product_urls,
        minimum,
        maximum,
    )
    payload = {
        "manifest": selection.path,
        "requested_crawl_mode": requested_mode,
        "resolved_crawl_mode": resolved_mode,
        "catalog_records_seen": selection.catalog_records_seen,
        "catalog_duplicates": selection.catalog_duplicate_records,
        "rejected_non_catalogs": selection.rejected_non_catalogs,
        "eligible_catalogs": len(selection.catalogs),
        "selected_catalogs": len(selected_catalogs),
        "catalog_sample": [asdict(item) for item in selected_catalogs[:sample]],
        "direct_records_seen": selection.records_seen,
        "direct_duplicates": selection.duplicate_records,
        "rejected_non_products": selection.rejected_non_products,
        "eligible_direct_product_urls": len(selection.product_urls),
        "phone_range": {
            "minimum": minimum,
            "maximum": maximum,
            "inclusive": True,
        },
        "selected_direct_in_range": len(selected_products),
        "direct_product_sample": selected_products[:sample],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def build_navigator(args: argparse.Namespace, proxies: Sequence[dict]) -> GsmarenaNavigator:
    evasion = GsmarenaEvasion(
        proxies=proxies,
        minimum_delay=args.delay_min,
        maximum_delay=args.delay_max,
    )
    return GsmarenaNavigator(
        evasion=evasion,
        headless=not args.headed,
        navigation_timeout_ms=args.navigation_timeout_ms,
        selector_timeout_ms=args.selector_timeout_ms,
        block_assets=not args.load_assets,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    if args.url and args.sitemap:
        parser.error("Choose either a positional URL or --sitemap, not both")
    if not args.url and args.sitemap is None:
        args.sitemap = DEFAULT_MANIFEST_PATH
    if args.delay_max < args.delay_min:
        parser.error("--delay-max must be greater than or equal to --delay-min")

    try:
        range_minimum, range_maximum = resolve_phone_range(
            args.min_phone,
            args.max_phone,
            args.limit,
        )
    except ValueError as exc:
        parser.error(str(exc))

    try:
        proxies = load_proxies(args.proxy, args.proxy_file)
    except ValueError as exc:
        parser.error(str(exc))

    if args.sitemap is not None:
        try:
            selection = load_manifest(args.sitemap)
        except ValueError as exc:
            log.error("%s", exc)
            return 2

        if args.dry_run:
            manifest_dry_run(
                selection,
                requested_mode=args.crawl_mode,
                maker_filters=args.maker,
                catalog_limit=args.catalog_limit,
                minimum=range_minimum,
                maximum=range_maximum,
                sample=args.sample,
            )
            resolved = resolve_crawl_mode(selection, args.crawl_mode)
            has_input = bool(selection.catalogs) if resolved == "catalog" else bool(selection.product_urls)
            return 0 if has_input else 1

        navigator = build_navigator(args, proxies)
        resolved_mode = resolve_crawl_mode(selection, args.crawl_mode)
        if resolved_mode == "catalog":
            catalogs = select_catalogs(
                selection.catalogs,
                args.maker,
                args.catalog_limit,
            )
            if not catalogs:
                log.error(
                    "No maker catalog pages matched. Regenerate the manifest "
                    "with FilterMobileUrls.py or change --maker/--crawl-mode."
                )
                return 1
            return crawl_catalogs(
                selection,
                catalogs,
                args.output_dir,
                minimum=range_minimum,
                maximum=range_maximum,
                force=args.force,
                retries=args.retries,
                navigator=navigator,
            )

        if not selection.product_urls:
            log.error("Manifest contains no recognized direct product URLs")
            return 1
        return crawl_manifest(
            selection,
            args.output_dir,
            minimum=range_minimum,
            maximum=range_maximum,
            force=args.force,
            retries=args.retries,
            navigator=navigator,
        )

    product_match = gsmarena_product_match(args.url)
    catalog_match = gsmarena_catalog_match(args.url)
    if product_match is None and catalog_match is None:
        log.error("Not a recognized GSMArena product or maker URL: %s", args.url)
        return 2
    if args.dry_run:
        print(
            json.dumps(
                {
                    "url": args.url,
                    "kind": "product" if product_match else "maker_catalog",
                    "valid": True,
                },
                indent=2,
            )
        )
        return 0

    navigator = build_navigator(args, proxies)
    if catalog_match is not None:
        catalog = CatalogSeed.from_url(args.url)
        selection = ManifestSelection(
            path=args.url,
            catalog_records_seen=1,
            catalog_duplicate_records=0,
            rejected_non_catalogs=0,
            catalogs=[catalog],
            records_seen=0,
            duplicate_records=0,
            rejected_non_products=0,
            product_urls=[],
        )
        return crawl_catalogs(
            selection,
            [catalog],
            args.output_dir,
            minimum=range_minimum,
            maximum=range_maximum,
            force=args.force,
            retries=args.retries,
            navigator=navigator,
        )

    try:
        with navigator:
            result = navigator.fetch_product(args.url)
    except Exception as exc:
        log.error("Single-page scrape failed: %s", exc)
        return 1

    output = result["raw"] if args.raw else result["template"]
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
