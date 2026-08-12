"""
treeConstructor.py

Reads a site list file, discovers each site's sitemap via robots.txt
(falling back to common sitemap paths), downloads and parses the
sitemap (including nested sitemap indexes and gzip'd sitemaps), builds
a tree structure of the site's URL paths, and saves one JSON file per
site to filestorage/sitemap/<sitename>.json.

Usage:
    python treeConstructor.py
    python treeConstructor.py --input backend/site-list.txt
    python treeConstructor.py --input backend/site-list.txt --output filestorage/sitemap

Notes on politeness / avoiding IP bans:
    - A single requests.Session is reused (connection pooling, one
      User-Agent) for every request.
    - Every request is followed by a randomized delay (see MIN_DELAY /
      MAX_DELAY below).
    - Failed requests are retried with exponential backoff + jitter.
    - Requests are fully sequential (no threads/concurrency) and are
      further throttled per-domain so we never hammer one host.
    - robots.txt is always checked first and its listed sitemap(s) are
      preferred over guessing paths.

Entries under an "UNAUTHORIZED_SITES:" section in the input file are
intentionally skipped -- that label is a clear signal scraping isn't
authorized for those hosts.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import random
import re
import sys
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse, urljoin
from xml.etree import ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

DEFAULT_INPUT = "backend/site-list.txt"
DEFAULT_OUTPUT_DIR = "filestorage/sitemap"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "MobileInfoAnalyticsBot/1.0 (+sitemap-crawler; contact: local-use-only)"
)

REQUEST_TIMEOUT = 15          # seconds
MIN_DELAY = 1.5                # seconds, minimum pause between requests
MAX_DELAY = 3.5                # seconds, maximum pause between requests
MAX_RETRIES = 4
BACKOFF_FACTOR = 2.0           # exponential backoff base
MAX_SITEMAP_DEPTH = 5          # guard against pathological sitemap-index loops
MAX_URLS_PER_SITE = 200_000    # sanity cap so a runaway sitemap can't eat all memory

COMMON_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap/sitemap.xml",
    "/wp-sitemap.xml",
]

SKIP_SECTIONS = {"UNAUTHORIZED_SITES"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("treeConstructor")


# --------------------------------------------------------------------------
# HTTP session
# --------------------------------------------------------------------------

def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def polite_sleep() -> None:
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def safe_get(session: requests.Session, url: str) -> Optional[requests.Response]:
    """GET a url with our own retry loop on top of the session's, so a
    fully-failed fetch (e.g. connection refused) also backs off politely
    instead of hammering a dead/blocking host."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            polite_sleep()
            if resp.status_code == 200:
                return resp
            if resp.status_code == 404:
                return None
            log.warning("GET %s -> HTTP %s (attempt %d/%d)", url, resp.status_code, attempt, MAX_RETRIES)
        except requests.RequestException as exc:
            log.warning("GET %s failed: %s (attempt %d/%d)", url, exc, attempt, MAX_RETRIES)
        # extra manual backoff on top of urllib3's, since this is a fresh attempt loop
        time.sleep((BACKOFF_FACTOR ** attempt) + random.uniform(0, 1))
    log.error("Giving up on %s after %d attempts", url, MAX_RETRIES)
    return None


# --------------------------------------------------------------------------
# Input file parsing
# --------------------------------------------------------------------------

def read_site_list(path: Path) -> Dict[str, List[str]]:
    """Parses a file shaped like:

        MAIN_SITE:
        https://example.com
        SITES:
        https://a.com
        https://b.com
        UNAUTHORIZED_SITES:
        https://c.com

    into {"MAIN_SITE": [...], "SITES": [...], "UNAUTHORIZED_SITES": [...]}.
    Unlabeled leading lines (before any section header) are ignored.
    """
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None

    header_re = re.compile(r"^([A-Z_][A-Z0-9_]*):\s*$")

    text = path.read_text(encoding="utf-8-sig")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = header_re.match(line)
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
            continue
        if current is None:
            log.warning("Ignoring line before any section header: %r", line)
            continue
        if line.startswith("http://") or line.startswith("https://"):
            sections[current].append(line)
        else:
            log.warning("Ignoring non-URL line under %s: %r", current, line)

    return sections


def sitename_from_url(url: str) -> str:
    """Turns a base URL into a filesystem-safe site name, e.g.
    'https://www.priceoye.pk/mobiles/' -> 'priceoye.pk'"""
    netloc = urlparse(url).netloc.lower()
    netloc = re.sub(r"^www\.", "", netloc)
    netloc = re.sub(r"[^a-z0-9.\-]", "_", netloc)
    return netloc or re.sub(r"[^a-z0-9.\-]", "_", url.lower())


# --------------------------------------------------------------------------
# robots.txt / sitemap discovery
# --------------------------------------------------------------------------

def get_sitemaps_from_robots(session: requests.Session, base_url: str) -> List[str]:
    robots_url = urljoin(base_url, "/robots.txt")
    resp = safe_get(session, robots_url)
    if resp is None:
        log.info("No robots.txt at %s", robots_url)
        return []

    sitemaps: List[str] = []
    for line in resp.text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            sm_url = line.split(":", 1)[1].strip()
            if sm_url:
                sitemaps.append(sm_url)

    if sitemaps:
        log.info("Found %d sitemap(s) in robots.txt for %s", len(sitemaps), base_url)
    return sitemaps


def discover_sitemaps(session: requests.Session, base_url: str) -> List[str]:
    sitemaps = get_sitemaps_from_robots(session, base_url)
    if sitemaps:
        return sitemaps

    log.info("No sitemap listed in robots.txt for %s, trying common paths", base_url)
    found = []
    for path in COMMON_SITEMAP_PATHS:
        candidate = urljoin(base_url, path)
        resp = safe_get(session, candidate)
        if resp is not None:
            log.info("Found sitemap at fallback path: %s", candidate)
            found.append(candidate)
            break  # one is enough; parse_sitemap will follow indexes if needed
    return found


# --------------------------------------------------------------------------
# Sitemap parsing (handles sitemap indexes + gzip, recursively)
# --------------------------------------------------------------------------

XML_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _decode_body(url: str, resp: requests.Response) -> Optional[bytes]:
    body = resp.content
    if url.lower().endswith(".gz") or resp.headers.get("Content-Type", "").endswith("gzip"):
        try:
            body = gzip.decompress(body)
        except OSError:
            # not actually gzipped despite the extension/header; fall through
            pass
    return body


def parse_sitemap(
    session: requests.Session,
    sitemap_url: str,
    collected: List[str],
    visited: Set[str],
    depth: int = 0,
) -> None:
    if sitemap_url in visited:
        return
    visited.add(sitemap_url)

    if depth > MAX_SITEMAP_DEPTH:
        log.warning("Max sitemap-index depth exceeded at %s, stopping recursion", sitemap_url)
        return
    if len(collected) >= MAX_URLS_PER_SITE:
        return

    resp = safe_get(session, sitemap_url)
    if resp is None:
        log.warning("Could not fetch sitemap %s", sitemap_url)
        return

    body = _decode_body(sitemap_url, resp)
    if not body:
        return

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        log.warning("Could not parse XML at %s: %s", sitemap_url, exc)
        return

    root_tag = _strip_ns(root.tag)

    if root_tag == "sitemapindex":
        child_sitemaps = []
        for sitemap_el in root:
            if _strip_ns(sitemap_el.tag) != "sitemap":
                continue
            loc_el = next((c for c in sitemap_el if _strip_ns(c.tag) == "loc"), None)
            if loc_el is not None and loc_el.text:
                child_sitemaps.append(loc_el.text.strip())
        log.info("%s is a sitemap index with %d child sitemap(s)", sitemap_url, len(child_sitemaps))
        for child_url in child_sitemaps:
            if len(collected) >= MAX_URLS_PER_SITE:
                break
            parse_sitemap(session, child_url, collected, visited, depth=depth + 1)

    elif root_tag == "urlset":
        count_before = len(collected)
        for url_el in root:
            if _strip_ns(url_el.tag) != "url":
                continue
            loc_el = next((c for c in url_el if _strip_ns(c.tag) == "loc"), None)
            if loc_el is not None and loc_el.text:
                collected.append(loc_el.text.strip())
                if len(collected) >= MAX_URLS_PER_SITE:
                    break
        log.info("%s contributed %d URL(s)", sitemap_url, len(collected) - count_before)

    else:
        log.warning("Unrecognized sitemap root element <%s> at %s", root_tag, sitemap_url)


def get_all_urls_for_site(session: requests.Session, base_url: str) -> List[str]:
    sitemap_urls = discover_sitemaps(session, base_url)
    if not sitemap_urls:
        log.warning("No sitemap could be found for %s", base_url)
        return []

    collected: List[str] = []
    visited: Set[str] = set()
    for sm_url in sitemap_urls:
        if len(collected) >= MAX_URLS_PER_SITE:
            break
        parse_sitemap(session, sm_url, collected, visited)

    # de-duplicate while preserving order
    seen = set()
    deduped = []
    for u in collected:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


# --------------------------------------------------------------------------
# Tree building
# --------------------------------------------------------------------------

@dataclass
class TreeNode:
    name: str
    path: str
    url: Optional[str] = None
    children: Dict[str, "TreeNode"] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "url": self.url,
            "children": [child.to_dict() for child in self.children.values()],
        }


def build_tree(base_url: str, urls: Iterable[str]) -> dict:
    parsed_base = urlparse(base_url)
    root = TreeNode(name=parsed_base.netloc or base_url, path="/", url=base_url)

    for url in urls:
        parsed = urlparse(url)
        segments = [seg for seg in parsed.path.split("/") if seg]

        node = root
        current_path = ""
        for seg in segments:
            current_path += "/" + seg
            if seg not in node.children:
                node.children[seg] = TreeNode(name=seg, path=current_path)
            node = node.children[seg]

        # the final segment's node represents this actual page
        node.url = url
        if parsed.query:
            # keep query strings out of the tree shape, but preserve one
            # example full URL with query on the node if it didn't have one
            if node.url is None:
                node.url = url

    return root.to_dict()


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def process_site(session: requests.Session, base_url: str, output_dir: Path) -> None:
    name = sitename_from_url(base_url)
    log.info("=== Processing %s (%s) ===", name, base_url)

    urls = get_all_urls_for_site(session, base_url)
    if not urls:
        log.warning("Skipping tree/JSON output for %s: no URLs discovered", name)
        return

    log.info("Building tree for %s from %d URL(s)", name, len(urls))
    tree = build_tree(base_url, urls)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{name}.json"
    payload = {
        "site": name,
        "base_url": base_url,
        "url_count": len(urls),
        "tree": tree,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Saved %s (%d URLs) -> %s", name, len(urls), out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sitemap tree JSONs for a list of sites.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Path to site-list.txt")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR, help="Output directory for JSON trees")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)

    if not input_path.exists():
        log.error("Input file not found: %s", input_path)
        sys.exit(1)

    sections = read_site_list(input_path)

    skipped = [s for s in sections if s in SKIP_SECTIONS]
    for s in skipped:
        log.info("Skipping section %s (%d site(s)) -- not authorized to scrape", s, len(sections[s]))

    sites_to_process: List[str] = []
    for section_name, urls in sections.items():
        if section_name in SKIP_SECTIONS:
            continue
        sites_to_process.extend(urls)

    # de-dupe while preserving order (MAIN_SITE might overlap with SITES)
    seen = set()
    ordered_sites = []
    for u in sites_to_process:
        if u not in seen:
            seen.add(u)
            ordered_sites.append(u)

    if not ordered_sites:
        log.error("No authorized sites found in %s", input_path)
        sys.exit(1)

    log.info("Will process %d site(s): %s", len(ordered_sites), ordered_sites)

    session = build_session()
    for base_url in ordered_sites:
        try:
            process_site(session, base_url, output_dir)
        except Exception as exc:  # keep going even if one site blows up
            log.exception("Unexpected error processing %s: %s", base_url, exc)
        # extra courtesy pause between switching hosts
        polite_sleep()

    log.info("Done.")


if __name__ == "__main__":
    main()