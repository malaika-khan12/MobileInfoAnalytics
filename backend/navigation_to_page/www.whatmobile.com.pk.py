"""Conservative, resumable Playwright crawler for WhatMobile product pages."""
from __future__ import annotations
import argparse, importlib.util, json, logging, random, re, sys, time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import unquote, urljoin, urlparse

LOG = logging.getLogger("whatmobile.navigator")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "filestorage/sitemap_mobile/whatmobile.com.pk.json"
DEFAULT_OUTPUT = ROOT / "filestorage/mobiles/whatmobile.com.pk"
SCRAPER_PATH = Path(__file__).resolve().parents[1] / "scrapers/www.whatmobile.com.pk.py"
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
PRODUCT = re.compile(r"^[A-Za-z][A-Za-z0-9']*_[A-Za-z0-9][A-Za-z0-9_]*-[A-Za-z0-9][A-Za-z0-9-]*$")
CATALOG = re.compile(r"^(?:[A-Za-z][A-Za-z0-9']*_)?(?:Mobiles_Prices|\d+_to_\d+_Mobiles)$", re.I)

def canonical_site(value: str) -> str:
    return re.sub(r"^www\.", "", urlparse(value if "://" in value else "https://" + value).netloc.lower().split(":")[0])
def whatmobile_product_match(url: str) -> bool:
    p=urlparse(url); return canonical_site(url)=="whatmobile.com.pk" and not p.query and not p.fragment and bool(PRODUCT.fullmatch(unquote(Path(p.path).name)))
def whatmobile_catalog_match(url: str) -> bool:
    p=urlparse(url); return canonical_site(url)=="whatmobile.com.pk" and not p.query and not p.fragment and bool(CATALOG.fullmatch(unquote(Path(p.path).name)))
def output_filename(url: str) -> str:
    name=INVALID_FILENAME.sub("_", unquote(Path(urlparse(url).path).name)).rstrip(". ")
    if not name: raise ValueError(f"Cannot derive output name from {url!r}")
    return f"whatmobile__{name}.json"
def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); tmp=path.with_name(path.name+".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False)+"\n", encoding="utf-8"); tmp.replace(path)
def valid_existing_output(path: Path) -> bool:
    try: return bool(json.loads(path.read_text(encoding="utf-8")).get("MobileName"))
    except (OSError, ValueError): return False
def utc_now() -> str: return datetime.now(timezone.utc).isoformat(timespec="seconds")
def positive_int(value: str) -> int:
    value=int(value)
    if value <= 0: raise argparse.ArgumentTypeError("value must be greater than zero")
    return value
def nonnegative_float(value: str) -> float:
    value=float(value)
    if value < 0: raise argparse.ArgumentTypeError("value must be zero or greater")
    return value
def resolve_range(minimum: int, maximum: Optional[int], limit: Optional[int]):
    if limit and maximum: raise ValueError("--limit cannot be combined with --max")
    maximum = minimum + limit - 1 if limit else maximum
    if maximum is not None and maximum < minimum:
        raise ValueError("--max must be greater than or equal to --min")
    return minimum, maximum

def load_scraper_class():
    spec=importlib.util.spec_from_file_location("whatmobile_scraper", SCRAPER_PATH)
    if not spec or not spec.loader: raise ImportError(f"Cannot load {SCRAPER_PATH}")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.WhatmobileScraper
def load_manifest(path: Path) -> list[str]:
    try: data=json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc: raise ValueError(f"Could not load {path}: {exc}") from exc
    candidates=data.get("catalog_urls") or data.get("mobile_urls", [])
    urls=[]; seen=set()
    for entry in candidates:
        url=entry.get("url") if isinstance(entry,dict) else entry
        if isinstance(url,str) and whatmobile_catalog_match(url) and url not in seen: seen.add(url); urls.append(url)
    return urls

class WhatmobileNavigator:
    def __init__(self, *, headless: bool, navigation_timeout_ms: int, selector_timeout_ms: int, delay_min: float, delay_max: float, load_assets: bool):
        self.headless=headless; self.navigation_timeout_ms=navigation_timeout_ms; self.selector_timeout_ms=selector_timeout_ms; self.delay_min=delay_min; self.delay_max=delay_max; self.load_assets=load_assets; self._playwright=None; self.browser=None
    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc: raise RuntimeError("Install requirements and run 'python -m playwright install chromium'.") from exc
        self._playwright=sync_playwright().start(); self.browser=self._playwright.chromium.launch(headless=self.headless); return self
    def __exit__(self,*_):
        if self.browser: self.browser.close()
        if self._playwright: self._playwright.stop()
    def _pause(self): time.sleep(random.uniform(self.delay_min,self.delay_max))
    def context(self): return self.browser.new_context(locale="en-PK", viewport={"width":1366,"height":900}, service_workers="block")
    def page(self, context):
        page=context.new_page()
        if not self.load_assets: page.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image","font","media"} else route.continue_())
        return page
    def discover(self, page, catalog_url: str) -> list[str]:
        response=page.goto(catalog_url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
        if response and response.status >=400: raise RuntimeError(f"HTTP {response.status} for {catalog_url}")
        page.wait_for_selector(".mobiles .item h4 a[href], h4.p4.biggertext a[href]", timeout=self.selector_timeout_ms)
        hrefs=page.eval_on_selector_all(".mobiles .item h4 a[href], h4.p4.biggertext a[href]", "els => els.map(e => e.getAttribute('href'))")
        urls=[]; seen=set()
        for href in hrefs:
            url=urljoin(page.url, href)
            if whatmobile_product_match(url) and url not in seen: seen.add(url); urls.append(url)
        self._pause()
        if not urls: raise RuntimeError(f"No product cards found on {catalog_url}")
        return urls
    def scrape(self,page,url):
        response=page.goto(url,wait_until="domcontentloaded",timeout=self.navigation_timeout_ms)
        if response and response.status>=400: raise RuntimeError(f"HTTP {response.status} for {url}")
        page.wait_for_selector("h1.hdng3, table.specs",timeout=self.selector_timeout_ms)
        if canonical_site(page.url)!="whatmobile.com.pk": raise RuntimeError(f"Unexpected redirect to {page.url}")
        scraper=load_scraper_class()(page.content(),source_url=url); result=scraper.to_template()
        self._pause()
        if not result.get("MobileName"): raise RuntimeError(f"No MobileName scraped from {url}")
        return result

@dataclass
class Stats:
    started_at: str; finished_at: Optional[str]=None; range_min: int=1; range_max: Optional[int]=None; catalogs: int=0; discovered: int=0; selected_urls: int=0; succeeded: int=0; skipped: int=0; failed: int=0

def crawl(catalogs: list[str], out: Path, args, minimum: int, maximum: Optional[int]) -> int:
    stats=Stats(started_at=utc_now(),range_min=minimum,range_max=maximum,catalogs=len(catalogs)); seen=set(); position=0
    failures=out / "_failures.jsonl"
    with WhatmobileNavigator(headless=not args.headed,navigation_timeout_ms=args.navigation_timeout_ms,selector_timeout_ms=args.selector_timeout_ms,delay_min=args.delay_min,delay_max=args.delay_max,load_assets=args.load_assets) as nav:
        for catalog in catalogs:
            context=nav.context(); listing=nav.page(context)
            try:
                for url in nav.discover(listing,catalog):
                    if url in seen: continue
                    seen.add(url); stats.discovered+=1; position+=1
                    if position < minimum: continue
                    if maximum is not None and position > maximum: break
                    stats.selected_urls+=1; target=out/output_filename(url)
                    if not args.force and valid_existing_output(target): stats.skipped+=1; continue
                    error=None
                    for _ in range(args.retries+1):
                        detail=None
                        try:
                            detail=nav.page(context); atomic_write_json(target,nav.scrape(detail,url)); stats.succeeded+=1; error=None; break
                        except Exception as exc: error=exc
                        finally:
                            if detail: detail.close()
                    if error:
                        stats.failed+=1; failures.parent.mkdir(parents=True,exist_ok=True)
                        with failures.open("a",encoding="utf-8") as fh: fh.write(json.dumps({"timestamp":utc_now(),"url":url,"error":str(error)})+"\n")
            finally: context.close()
            if maximum is not None and position >= maximum: break
    stats.finished_at=utc_now(); atomic_write_json(out/"_crawl_summary.json",asdict(stats)); LOG.info("saved=%d skipped=%d failed=%d",stats.succeeded,stats.skipped,stats.failed)
    return 1 if stats.failed else 0

def parser():
    p=argparse.ArgumentParser(description="Crawl WhatMobile catalog pages into normalized phone JSON.")
    p.add_argument("url",nargs="?",help="Optional WhatMobile catalog URL")
    p.add_argument("--sitemap",type=Path,default=DEFAULT_MANIFEST); p.add_argument("--output-dir",type=Path,default=DEFAULT_OUTPUT)
    p.add_argument("--min",dest="minimum",type=positive_int,default=1); p.add_argument("--max",dest="maximum",type=positive_int); p.add_argument("--limit",type=positive_int)
    p.add_argument("--dry-run",action="store_true"); p.add_argument("--headed",action="store_true"); p.add_argument("--force",action="store_true"); p.add_argument("--retries",type=lambda v:max(0,int(v)),default=2)
    p.add_argument("--delay-min",type=nonnegative_float,default=2.0); p.add_argument("--delay-max",type=nonnegative_float,default=5.0); p.add_argument("--navigation-timeout-ms",type=positive_int,default=30000); p.add_argument("--selector-timeout-ms",type=positive_int,default=15000); p.add_argument("--load-assets",action="store_true"); p.add_argument("--log-level",choices=["DEBUG","INFO","WARNING","ERROR"],default="INFO")
    return p
def main(argv: Optional[Sequence[str]]=None) -> int:
    args=parser().parse_args(argv); logging.basicConfig(level=getattr(logging,args.log_level),format="%(asctime)s [%(levelname)s] %(message)s")
    if args.delay_max < args.delay_min: parser().error("--delay-max must be greater than or equal to --delay-min")
    try: minimum,maximum=resolve_range(args.minimum,args.maximum,args.limit)
    except ValueError as exc: parser().error(str(exc))
    catalogs=[args.url] if args.url else load_manifest(args.sitemap)
    if not all(whatmobile_catalog_match(url) for url in catalogs): parser().error("URL/manifest contains an invalid WhatMobile catalog URL")
    if args.dry_run: print(json.dumps({"catalogs":catalogs,"range_min":minimum,"range_max":maximum,"strategy":"whatmobile_catalog_cards"},indent=2)); return 0 if catalogs else 1
    return crawl(catalogs,args.output_dir,args,minimum,maximum)
if __name__=="__main__": sys.exit(main())
