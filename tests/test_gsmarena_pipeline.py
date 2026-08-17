"""Offline tests for the GSMArena URL-filtering and manifest pipeline."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FILTER_PATH = PROJECT_ROOT / "filestorage" / "FilterMobileUrls.py"
NAVIGATOR_PATH = (
    PROJECT_ROOT / "backend" / "navigation_to_page" / "www.gsmarena.com.py"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mobile_filter = load_module("mobile_filter_under_test", FILTER_PATH)
navigator = load_module("gsmarena_navigator_under_test", NAVIGATOR_PATH)


PRODUCT_ONE = (
    "https://www.gsmarena.com/"
    "xiaomi_redmi_note_14_4g_(global)-13616.php"
)
PRODUCT_TWO = "https://www.gsmarena.com/apple_iphone_16_pro-13315.php"
CATALOG_XIAOMI = "https://www.gsmarena.com/xiaomi-phones-80.php"
CATALOG_SAMSUNG = "https://www.gsmarena.com/samsung-phones-9.php"
CATALOG_XIAOMI_PAGE_2 = (
    "https://www.gsmarena.com/xiaomi-phones-f-80-0-p2.php"
)
NON_PRODUCTS = [
    CATALOG_SAMSUNG,
    "https://www.gsmarena.com/i_mobile-phones-f-52-0-r1-p1.php",
    "https://www.gsmarena.com/xiaomi_redmi_note_14_4g-review-2798.php",
    "https://www.gsmarena.com/xiaomi_redmi_note_14_4g-pictures-13616.php",
    "https://www.gsmarena.com/search.php3",
]


def node(url: str) -> dict:
    path = "/" + url.rsplit("/", 1)[-1]
    return {"name": path[1:], "path": path, "url": url, "children": []}


def sample_tree_payload() -> dict:
    urls = [
        CATALOG_XIAOMI,
        NON_PRODUCTS[0],
        PRODUCT_ONE,
        NON_PRODUCTS[1],
        PRODUCT_TWO,
        *NON_PRODUCTS[2:],
    ]
    return {
        "site": "gsmarena.com",
        "base_url": "https://www.gsmarena.com",
        "url_count": len(urls),
        "tree": {
            "name": "www.gsmarena.com",
            "path": "/",
            "url": "https://www.gsmarena.com/",
            "children": [node(url) for url in urls],
        },
    }


class ProductRuleTests(unittest.TestCase):
    def test_filter_and_navigator_accept_the_same_products(self) -> None:
        for url in (PRODUCT_ONE, PRODUCT_TWO):
            self.assertIsNotNone(mobile_filter.gsmarena_product_match(url))
            self.assertIsNotNone(navigator.gsmarena_product_match(url))

        for url in NON_PRODUCTS:
            self.assertIsNone(mobile_filter.gsmarena_product_match(url))
            self.assertIsNone(navigator.gsmarena_product_match(url))

    def test_windows_safe_output_filename(self) -> None:
        self.assertEqual(
            navigator.output_filename(PRODUCT_ONE),
            "gsmarena__xiaomi_redmi_note_14_4g_(global)-13616.php.json",
        )

    def test_filter_and_navigator_accept_only_canonical_catalog_landings(self) -> None:
        for url in (CATALOG_XIAOMI, CATALOG_SAMSUNG):
            self.assertIsNotNone(mobile_filter.gsmarena_catalog_match(url))
            self.assertIsNotNone(navigator.gsmarena_catalog_match(url))

        self.assertIsNone(mobile_filter.gsmarena_catalog_match(CATALOG_XIAOMI_PAGE_2))
        self.assertIsNone(navigator.gsmarena_catalog_match(CATALOG_XIAOMI_PAGE_2))
        self.assertEqual(
            navigator.catalog_identity(CATALOG_XIAOMI_PAGE_2),
            ("xiaomi", 80),
        )


class FilterTests(unittest.TestCase):
    def test_auto_strategy_builds_catalog_tree_and_product_fallback(self) -> None:
        pattern = mobile_filter.build_keyword_pattern(["mobile"])
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "gsmarena.com.json"
            input_path.write_text(json.dumps(sample_tree_payload()), encoding="utf-8")
            result = mobile_filter.filter_site_file(
                input_path,
                pattern,
                mode="base",
                strategy="auto",
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["strategy"], "gsmarena_catalog_and_product_pages")
        self.assertEqual(result["mode"], "catalog_tree")
        self.assertEqual(result["catalog_count"], 2)
        self.assertEqual(result["match_count"], 2)
        self.assertEqual(
            [entry["url"] for entry in result["catalog_urls"]],
            [CATALOG_XIAOMI, CATALOG_SAMSUNG],
        )
        self.assertEqual(
            [entry["url"] for entry in result["tree"]["children"]],
            [CATALOG_XIAOMI, CATALOG_SAMSUNG],
        )
        self.assertEqual(
            [entry["url"] for entry in result["mobile_urls"]],
            [PRODUCT_ONE, PRODUCT_TWO],
        )

    def test_atomic_manifest_write_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            payload = {"mobile_urls": [{"url": PRODUCT_ONE}]}
            mobile_filter.atomic_write_json(path, payload)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)
            self.assertFalse(path.with_name(path.name + ".tmp").exists())


class ManifestTests(unittest.TestCase):
    def test_combined_manifest_prefers_fewer_request_direct_mode(self) -> None:
        payload = {
            "catalog_urls": [
                {"url": CATALOG_XIAOMI},
                {"url": CATALOG_SAMSUNG},
                {"url": CATALOG_XIAOMI},
            ],
            "mobile_urls": [{"url": PRODUCT_ONE}, {"url": PRODUCT_TWO}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gsmarena.com.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            selection = navigator.load_manifest(path)

        self.assertEqual(selection.catalog_records_seen, 3)
        self.assertEqual(selection.catalog_duplicate_records, 1)
        self.assertEqual(
            [catalog.url for catalog in selection.catalogs],
            [CATALOG_XIAOMI, CATALOG_SAMSUNG],
        )
        self.assertEqual(navigator.resolve_crawl_mode(selection, "auto"), "direct")

    def test_filtered_manifest_is_loaded_and_non_products_are_rejected(self) -> None:
        payload = {
            "mobile_urls": [
                {"url": PRODUCT_ONE},
                {"url": NON_PRODUCTS[0]},
                {"url": PRODUCT_TWO},
                {"url": PRODUCT_ONE},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gsmarena.com.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            selection = navigator.load_manifest(path)

        self.assertEqual(selection.records_seen, 4)
        self.assertEqual(selection.duplicate_records, 1)
        self.assertEqual(selection.rejected_non_products, 1)
        self.assertEqual(selection.product_urls, [PRODUCT_ONE, PRODUCT_TWO])

    def test_full_tree_input_is_supported_as_a_safety_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gsmarena.com.json"
            path.write_text(json.dumps(sample_tree_payload()), encoding="utf-8")
            selection = navigator.load_manifest(path)

        self.assertEqual(selection.product_urls, [PRODUCT_ONE, PRODUCT_TWO])
        self.assertEqual(
            [catalog.url for catalog in selection.catalogs],
            [CATALOG_XIAOMI, CATALOG_SAMSUNG],
        )

    def test_resume_validation_rejects_corrupt_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "phone.json"
            path.write_text("not json", encoding="utf-8")
            self.assertFalse(navigator.valid_existing_output(path))
            path.write_text(json.dumps({"MobileName": "Test Phone"}), encoding="utf-8")
            self.assertTrue(navigator.valid_existing_output(path))


class PhoneRangeTests(unittest.TestCase):
    def test_range_is_one_based_and_inclusive(self) -> None:
        urls = ["one", "two", "three", "four"]
        self.assertEqual(
            navigator.select_phone_range(urls, 2, 3),
            ["two", "three"],
        )
        self.assertEqual(
            navigator.select_phone_range(urls, 3, None),
            ["three", "four"],
        )

    def test_legacy_limit_becomes_a_range_length(self) -> None:
        self.assertEqual(
            navigator.resolve_phone_range(101, None, limit=5),
            (101, 105),
        )
        with self.assertRaises(ValueError):
            navigator.resolve_phone_range(1, 10, limit=5)

    def test_parser_accepts_short_and_long_range_names(self) -> None:
        short = navigator.build_parser().parse_args(["--min", "10", "--max", "20"])
        long = navigator.build_parser().parse_args(
            ["--minimum", "10", "--maximum", "20"]
        )
        self.assertEqual((short.min_phone, short.max_phone), (10, 20))
        self.assertEqual((long.min_phone, long.max_phone), (10, 20))

    def test_parser_defaults_to_conservative_request_policy(self) -> None:
        args = navigator.build_parser().parse_args([])
        self.assertEqual(args.retries, 0)
        self.assertEqual(args.delay_min, navigator.DEFAULT_DELAY_MIN_SECONDS)
        self.assertEqual(args.delay_max, navigator.DEFAULT_DELAY_MAX_SECONDS)
        self.assertEqual(args.hourly_limit, navigator.MAX_HOURLY_REQUESTS)
        self.assertEqual(args.daily_limit, navigator.MAX_DAILY_REQUESTS)
        self.assertEqual(args.session_limit, navigator.MAX_SESSION_REQUESTS)


class FakeClock:
    def __init__(self, value: float) -> None:
        self.value = value
        self.sleeps = []

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class RequestPolicyTests(unittest.TestCase):
    def make_policy(self, directory, clock, **overrides):
        options = {
            "minimum_delay": 60,
            "maximum_delay": 60,
            "hourly_limit": 3,
            "daily_limit": 4,
            "session_limit": 2,
            "clock": clock,
            "sleeper": clock.sleep,
            "uniform": lambda _minimum, _maximum: 60,
        }
        options.update(overrides)
        return navigator.PersistentRequestPolicy(Path(directory), **options)

    def test_retry_after_supports_seconds_and_http_date(self) -> None:
        self.assertEqual(navigator.parse_retry_after("36000", 1_700_000_000), 36000)
        future = datetime.fromtimestamp(1_700_000_120, timezone.utc)
        http_date = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
        self.assertEqual(
            navigator.parse_retry_after(http_date, 1_700_000_000),
            120,
        )
        self.assertIsNone(navigator.parse_retry_after("not-a-date"))

    def test_spacing_and_session_limit_persist_request_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clock = FakeClock(1_700_000_000)
            policy = self.make_policy(directory, clock)
            policy.acquire()
            try:
                policy.before_request(url=PRODUCT_ONE, kind="product")
                clock.value += 1
                policy.before_request(url=PRODUCT_TWO, kind="product")
                self.assertEqual(clock.sleeps, [59])
                with self.assertRaises(navigator.CrawlPolicyStop) as raised:
                    policy.before_request(url=PRODUCT_ONE, kind="product")
                self.assertEqual(raised.exception.reason, "session_limit")
            finally:
                policy.release()

            state = json.loads(
                (Path(directory) / navigator.POLICY_STATE_FILENAME).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(len(state["request_times_utc"]), 2)
            self.assertFalse((Path(directory) / navigator.CRAWL_LOCK_FILENAME).exists())

    def test_server_retry_after_is_not_capped_and_blocks_next_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clock = FakeClock(1_700_000_000)
            first = self.make_policy(directory, clock)
            first.acquire()
            try:
                resume_at = first.record_server_stop(
                    url=PRODUCT_ONE,
                    status=429,
                    retry_after_seconds=36_000,
                    reason="http_429",
                )
            finally:
                first.release()

            expected = navigator.epoch_to_utc(
                clock.value
                + 36_000
                + navigator.SERVER_COOLDOWN_BUFFER_SECONDS
            )
            self.assertEqual(resume_at, expected)

            second = self.make_policy(directory, clock)
            second.acquire()
            try:
                with self.assertRaises(navigator.CrawlPolicyStop) as raised:
                    second.before_request(url=PRODUCT_TWO, kind="product")
                self.assertEqual(raised.exception.reason, "cooldown_active")
                self.assertEqual(raised.exception.resume_at, expected)
                self.assertEqual(second.session_requests, 0)
            finally:
                second.release()

    def test_known_cooldown_stops_before_playwright_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clock = FakeClock(1_700_000_000)
            first = self.make_policy(directory, clock)
            first.acquire()
            try:
                first.record_server_stop(
                    url=PRODUCT_ONE,
                    status=429,
                    retry_after_seconds=36_000,
                    reason="http_429",
                )
            finally:
                first.release()

            second = self.make_policy(directory, clock)
            nav = navigator.GsmarenaNavigator(request_policy=second)
            original_import = navigator.import_playwright

            def forbidden_import():
                self.fail("Playwright import must not happen during cooldown")

            navigator.import_playwright = forbidden_import
            try:
                with self.assertRaises(navigator.CrawlPolicyStop):
                    nav.start()
            finally:
                navigator.import_playwright = original_import
                nav.close()

            self.assertFalse((Path(directory) / navigator.CRAWL_LOCK_FILENAME).exists())

    def test_hourly_limit_survives_process_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clock = FakeClock(1_700_000_000)
            first = self.make_policy(
                directory,
                clock,
                hourly_limit=1,
                session_limit=2,
            )
            first.acquire()
            try:
                first.before_request(url=PRODUCT_ONE, kind="product")
            finally:
                first.release()

            second = self.make_policy(
                directory,
                clock,
                hourly_limit=1,
                session_limit=2,
            )
            second.acquire()
            try:
                with self.assertRaises(navigator.CrawlPolicyStop) as raised:
                    second.before_request(url=PRODUCT_TWO, kind="product")
                self.assertEqual(raised.exception.reason, "hourly_limit")
                self.assertEqual(second.session_requests, 0)
            finally:
                second.release()


class FakeDirectNavigator:
    def __init__(self) -> None:
        self.scraped = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def fetch_product(self, url):
        self.scraped.append(url)
        return {"template": {"MobileName": url.rsplit("/", 1)[-1]}}

    def restart_browser(self) -> None:
        return None


class FakeRequestCounter:
    session_requests = 1


class FakePolicyStopNavigator(FakeDirectNavigator):
    def __init__(self) -> None:
        super().__init__()
        self.request_policy = FakeRequestCounter()
        self.attempts = 0

    def fetch_product(self, url):
        self.attempts += 1
        raise navigator.CrawlPolicyStop(
            "server says stop",
            reason="http_429",
            resume_at="2030-01-01T00:00:00+00:00",
            status=429,
            retry_after_seconds=36_000,
        )


class DirectCrawlRangeTests(unittest.TestCase):
    def test_direct_crawl_saves_only_the_inclusive_range(self) -> None:
        selection = navigator.ManifestSelection(
            path="synthetic-manifest.json",
            catalog_records_seen=0,
            catalog_duplicate_records=0,
            rejected_non_catalogs=0,
            catalogs=[],
            records_seen=2,
            duplicate_records=0,
            rejected_non_products=0,
            product_urls=[PRODUCT_ONE, PRODUCT_TWO],
        )
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            fake_nav = FakeDirectNavigator()
            code = navigator.crawl_manifest(
                selection,
                output_dir,
                minimum=2,
                maximum=2,
                force=False,
                retries=0,
                navigator=fake_nav,
            )

            self.assertEqual(code, 0)
            self.assertEqual(fake_nav.scraped, [PRODUCT_TWO])
            self.assertFalse(
                (output_dir / navigator.output_filename(PRODUCT_ONE)).exists()
            )
            self.assertTrue(
                (output_dir / navigator.output_filename(PRODUCT_TWO)).is_file()
            )
            summary = json.loads(
                (output_dir / "_crawl_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["range_min"], 2)
            self.assertEqual(summary["range_max"], 2)
            self.assertEqual(summary["selected_urls"], 1)

    def test_rate_limit_stops_immediately_without_retry_or_failure_record(self) -> None:
        selection = navigator.ManifestSelection(
            path="synthetic-manifest.json",
            catalog_records_seen=0,
            catalog_duplicate_records=0,
            rejected_non_catalogs=0,
            catalogs=[],
            records_seen=1,
            duplicate_records=0,
            rejected_non_products=0,
            product_urls=[PRODUCT_ONE],
        )
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            fake_nav = FakePolicyStopNavigator()
            code = navigator.crawl_manifest(
                selection,
                output_dir,
                minimum=1,
                maximum=1,
                force=False,
                retries=1,
                navigator=fake_nav,
            )

            self.assertEqual(code, navigator.POLICY_STOP_EXIT_CODE)
            self.assertEqual(fake_nav.attempts, 1)
            self.assertFalse((output_dir / "_failures.jsonl").exists())
            summary = json.loads(
                (output_dir / "_crawl_summary.json").read_text(encoding="utf-8")
            )
            self.assertTrue(summary["policy_stopped"])
            self.assertEqual(summary["policy_stop_reason"], "http_429")
            self.assertEqual(summary["server_status"], 429)
            self.assertEqual(summary["retry_after_seconds"], 36_000)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["document_requests_this_run"], 1)


class RecordingServerStopPolicy:
    def __init__(self) -> None:
        self.recorded = None

    def record_server_stop(self, **kwargs):
        self.recorded = kwargs
        return "2030-01-01T00:00:00+00:00"


class HttpRefusalTests(unittest.TestCase):
    def test_429_records_full_retry_after_and_raises_policy_stop(self) -> None:
        policy = RecordingServerStopPolicy()
        nav = navigator.GsmarenaNavigator(request_policy=policy)
        response = type(
            "Response",
            (),
            {"status": 429, "headers": {"retry-after": "36000"}},
        )()

        with self.assertRaises(navigator.CrawlPolicyStop) as raised:
            nav._guard_response(response, PRODUCT_ONE)

        self.assertEqual(raised.exception.reason, "http_429")
        self.assertEqual(raised.exception.retry_after_seconds, 36_000)
        self.assertEqual(policy.recorded["retry_after_seconds"], 36_000)


class FakeFrame:
    def __init__(self, parent_frame=None) -> None:
        self.parent_frame = parent_frame


class FakeRouteRequest:
    def __init__(self, resource_type, url, parent_frame=None) -> None:
        self.resource_type = resource_type
        self.url = url
        self.frame = FakeFrame(parent_frame)


class FakeRoute:
    def __init__(self, request) -> None:
        self.request = request
        self.action = None

    def abort(self, *_args) -> None:
        self.action = "abort"

    def continue_(self) -> None:
        self.action = "continue"


class RequestRoutingTests(unittest.TestCase):
    def test_only_same_site_main_document_is_allowed(self) -> None:
        main = FakeRoute(
            FakeRouteRequest("document", PRODUCT_ONE, parent_frame=None)
        )
        navigator.GsmarenaNavigator._route_request(main)
        self.assertEqual(main.action, "continue")

        for route in (
            FakeRoute(FakeRouteRequest("image", PRODUCT_ONE)),
            FakeRoute(FakeRouteRequest("script", PRODUCT_ONE)),
            FakeRoute(
                FakeRouteRequest(
                    "document",
                    PRODUCT_ONE,
                    parent_frame=FakeFrame(),
                )
            ),
            FakeRoute(
                FakeRouteRequest(
                    "document",
                    "https://ads.example.test/frame",
                    parent_frame=FakeFrame(),
                )
            ),
        ):
            navigator.GsmarenaNavigator._route_request(route)
            self.assertEqual(route.action, "abort")


class FakeResponse:
    status = 200


class FakeCatalogPage:
    def __init__(self) -> None:
        self.url = CATALOG_XIAOMI

    def goto(self, url, **_kwargs):
        self.url = url
        return FakeResponse()

    def wait_for_selector(self, _selector, **_kwargs) -> None:
        return None

    def eval_on_selector_all(self, selector, _script):
        if selector == ".makers a[href]":
            return [
                "/xiaomi_redmi_note_14_4g_(global)-13616.php",
                "/xiaomi_redmi_note_14_4g-review-2798.php",
                "/apple_iphone_16_pro-13315.php",
            ]
        return [
            "/xiaomi-phones-f-80-0-p2.php",
            "/samsung-phones-f-9-0-p2.php",
            "/xiaomi-phones-80.php",
        ]


class CatalogDiscoveryTests(unittest.TestCase):
    def test_catalog_page_discovers_products_and_same_maker_pagination(self) -> None:
        nav = navigator.GsmarenaNavigator()
        result = nav.discover_catalog_page(
            FakeCatalogPage(),
            CATALOG_XIAOMI,
            ("xiaomi", 80),
        )
        self.assertEqual(result["product_urls"], [PRODUCT_ONE, PRODUCT_TWO])
        self.assertEqual(result["pagination_urls"], [CATALOG_XIAOMI_PAGE_2])


class FakeBrowserPage:
    def __init__(self) -> None:
        self.closed = False

    def bring_to_front(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeBrowserContext:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeCatalogNavigator:
    def __init__(self) -> None:
        self.scraped = []
        self.catalog_visits = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def new_context(self):
        return FakeBrowserContext()

    def new_page(self, _context):
        return FakeBrowserPage()

    def discover_catalog_page(self, _page, url, _identity):
        self.catalog_visits.append(url)
        if url == CATALOG_XIAOMI:
            return {
                "url": url,
                "final_url": url,
                "product_urls": [PRODUCT_ONE],
                "pagination_urls": [CATALOG_XIAOMI_PAGE_2],
            }
        return {
            "url": url,
            "final_url": url,
            "product_urls": [PRODUCT_ONE, PRODUCT_TWO],
            "pagination_urls": [],
        }

    def scrape_product_on_page(self, _page, url):
        self.scraped.append(url)
        return {"template": {"MobileName": url.rsplit("/", 1)[-1]}}


class CatalogCrawlTests(unittest.TestCase):
    def make_selection(self):
        catalog = navigator.CatalogSeed.from_url(CATALOG_XIAOMI)
        return navigator.ManifestSelection(
            path="synthetic-manifest.json",
            catalog_records_seen=1,
            catalog_duplicate_records=0,
            rejected_non_catalogs=0,
            catalogs=[catalog],
            records_seen=2,
            duplicate_records=0,
            rejected_non_products=0,
            product_urls=[PRODUCT_ONE, PRODUCT_TWO],
        )

    def test_catalog_crawl_follows_pagination_saves_and_resumes(self) -> None:
        selection = self.make_selection()
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            first_nav = FakeCatalogNavigator()
            first_code = navigator.crawl_catalogs(
                selection,
                selection.catalogs,
                output_dir,
                minimum=1,
                maximum=None,
                force=False,
                retries=0,
                navigator=first_nav,
            )
            self.assertEqual(first_code, 0)
            self.assertEqual(
                first_nav.catalog_visits,
                [CATALOG_XIAOMI, CATALOG_XIAOMI_PAGE_2],
            )
            self.assertEqual(first_nav.scraped, [PRODUCT_ONE, PRODUCT_TWO])
            self.assertTrue(
                (output_dir / navigator.output_filename(PRODUCT_ONE)).is_file()
            )
            self.assertTrue(
                (output_dir / navigator.output_filename(PRODUCT_TWO)).is_file()
            )

            coverage = json.loads(
                (output_dir / "_catalog_coverage.json").read_text(encoding="utf-8")
            )
            self.assertTrue(coverage["complete_catalog_scan"])
            self.assertEqual(coverage["overlap_count"], 2)

            second_nav = FakeCatalogNavigator()
            second_code = navigator.crawl_catalogs(
                selection,
                selection.catalogs,
                output_dir,
                minimum=1,
                maximum=None,
                force=False,
                retries=0,
                navigator=second_nav,
            )
            self.assertEqual(second_code, 0)
            self.assertEqual(second_nav.scraped, [])
            summary = json.loads(
                (output_dir / "_crawl_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["already_complete"], 2)

    def test_catalog_crawl_processes_only_the_inclusive_phone_range(self) -> None:
        selection = self.make_selection()
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            fake_nav = FakeCatalogNavigator()
            code = navigator.crawl_catalogs(
                selection,
                selection.catalogs,
                output_dir,
                minimum=2,
                maximum=2,
                force=False,
                retries=0,
                navigator=fake_nav,
            )

            self.assertEqual(code, 0)
            self.assertEqual(fake_nav.scraped, [PRODUCT_TWO])
            self.assertFalse(
                (output_dir / navigator.output_filename(PRODUCT_ONE)).exists()
            )
            self.assertTrue(
                (output_dir / navigator.output_filename(PRODUCT_TWO)).is_file()
            )
            summary = json.loads(
                (output_dir / "_crawl_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["range_min"], 2)
            self.assertEqual(summary["range_max"], 2)
            self.assertEqual(summary["range_skipped_before_min"], 1)
            self.assertEqual(summary["selected_urls"], 1)


if __name__ == "__main__":
    unittest.main()
