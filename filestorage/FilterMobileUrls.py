"""
FilterMobileUrls.py

Reads the site-tree JSON files produced by treeConstructor.py
(filestorage/sitemap/<site>.json, shape: {site, base_url, url_count, tree})
and filters each tree down to just the branches that are about mobile
phones -- e.g. a path segment like "mobiles", "mobile_products",
"mobile-phones", etc.

Rather than dumping every individual product URL under a matched branch
(which is what you said you don't want -- a single mobile section can
contain thousands of product pages), this walks each tree top-down and
stops at the FIRST node along a path whose path/url matches the keyword
regex. That node's URL is the "base URL" for that mobile section. It
does not descend further into that branch, since everything under a
matched node is already part of the mobile section.

Example: given a tree containing
    /electronics/laptops/...
    /mobiles/samsung/galaxy-s24
    /mobiles/apple/iphone-15
    /garments/mens/...
this produces one base URL: https://site.com/mobiles/
(it does NOT also list /mobiles/samsung/ and /mobiles/samsung/galaxy-s24
separately -- those are nested under the already-matched /mobiles/ node).

If a matching path segment was never itself a standalone page in the
sitemap (node.url is None -- only its children had actual URLs), the
base URL is constructed from base_url + path and flagged
"url_is_inferred": true so you know it's a guess, not a confirmed page.

Usage:
    python FilterMobileUrls.py
    python FilterMobileUrls.py --input-dir filestorage/sitemap --output-dir filestorage/sitemap_mobile
    python FilterMobileUrls.py --keywords mobile,smartphone,cell-phone
    python FilterMobileUrls.py --mode all   # list every matching URL instead of just branch bases
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("FilterMobileUrls")

DEFAULT_INPUT_DIR = "filestorage/sitemap"
DEFAULT_OUTPUT_DIR = "filestorage/sitemap_mobile"
DEFAULT_KEYWORDS = ["mobile"]  # substring match already covers "mobiles",
                                 # "mobile_products", "mobile-phones", etc.


def build_keyword_pattern(keywords: List[str]) -> re.Pattern:
    escaped = [re.escape(k.strip()) for k in keywords if k.strip()]
    if not escaped:
        raise ValueError("At least one keyword is required")
    pattern = "|".join(escaped)
    return re.compile(pattern, re.IGNORECASE)


def count_urls(node: dict) -> int:
    """Counts how many nodes in this subtree have an actual URL -- gives a
    sense of how many pages live under a matched mobile branch without
    listing them all."""
    count = 1 if node.get("url") else 0
    for child in node.get("children", []):
        count += count_urls(child)
    return count


def url_path_only(url: str) -> str:
    """Strips scheme+domain from a URL, keeping only the path (+query).
    Matching must never be done against the full URL -- some of these
    sites (whatmobile.com.pk, mymobile.pk, whatamobile.com.pk) have
    'mobile' baked into the domain name itself, which would otherwise
    make every single page on the site match regardless of its actual
    path."""
    parsed = urlparse(url)
    return parsed.path + ("?" + parsed.query if parsed.query else "")


def node_matches(node: dict, pattern: re.Pattern) -> bool:
    path = node.get("path") or ""
    if pattern.search(path):
        return True
    url = node.get("url") or ""
    if url and pattern.search(url_path_only(url)):
        return True
    return False


def find_mobile_branches(node: dict, pattern: re.Pattern, results: List[dict]) -> None:
    """DFS that stops descending as soon as it finds a match, since
    everything below a matched node is already part of that mobile
    section."""
    if node_matches(node, pattern):
        results.append(node)
        return  # do not descend further -- this whole branch is "mobile"

    for child in node.get("children", []):
        find_mobile_branches(child, pattern, results)


def find_all_matching_urls(node: dict, pattern: re.Pattern, results: List[dict]) -> None:
    """Alternative walk for --mode all: collects every node with a URL
    whose path/url matches, without stopping at the first match. Used
    when you actually want the full flat list rather than just branch
    bases."""
    if node.get("url") and node_matches(node, pattern):
        results.append(node)
    for child in node.get("children", []):
        find_all_matching_urls(child, pattern, results)


def domain_root(base_url: str) -> str:
    """base_url in the tree JSON can be a subpath (e.g. https://site.com/mobiles/),
    not the site root -- so inferred URLs must be built from scheme+netloc only,
    never from base_url directly, or paths outside that subpath come out wrong."""
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def build_base_entry(node: dict, base_url: str, pattern: re.Pattern) -> dict:
    url = node.get("url")
    inferred = False
    if not url:
        url = domain_root(base_url) + node.get("path", "")
        inferred = True

    match = pattern.search(node.get("path") or url)

    return {
        "url": url,
        "path": node.get("path"),
        "matched_keyword": match.group(0) if match else None,
        "url_is_inferred": inferred,
        "url_count_in_branch": count_urls(node),
    }


def build_flat_entry(node: dict, pattern: re.Pattern) -> dict:
    match = pattern.search(node.get("path") or node.get("url") or "")
    return {
        "url": node["url"],
        "path": node.get("path"),
        "matched_keyword": match.group(0) if match else None,
    }


def filter_site_file(path: Path, pattern: re.Pattern, mode: str) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Could not read %s: %s", path, exc)
        return None

    tree = data.get("tree")
    base_url = data.get("base_url", "")
    site = data.get("site", path.stem)

    if not tree:
        log.warning("%s has no 'tree' field, skipping", path.name)
        return None

    if mode == "base":
        matches: List[dict] = []
        for child in tree.get("children", []):
            find_mobile_branches(child, pattern, matches)
        entries = [build_base_entry(n, base_url, pattern) for n in matches]
    else:  # mode == "all"
        matches = []
        for child in tree.get("children", []):
            find_all_matching_urls(child, pattern, matches)
        entries = [build_flat_entry(n, pattern) for n in matches]

    return {
        "site": site,
        "base_url": base_url,
        "source_url_count": data.get("url_count"),
        "mode": mode,
        "match_count": len(entries),
        "mobile_urls": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter site-tree JSONs down to mobile-phone URL branches.")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR, help="Directory of <site>.json tree files")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Where to write filtered JSON files")
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help="Comma-separated substrings to match (case-insensitive) against URL paths, e.g. 'mobile,smartphone'",
    )
    parser.add_argument(
        "--mode",
        choices=["base", "all"],
        default="base",
        help="'base' (default): just the top-most matching URL per branch. "
             "'all': every individual matching URL in the tree, no stopping at first match.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    keywords = [k for k in args.keywords.split(",") if k.strip()]
    pattern = build_keyword_pattern(keywords)

    if not input_dir.exists():
        log.error("Input directory not found: %s", input_dir)
        sys.exit(1)

    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        log.error("No .json files found in %s", input_dir)
        sys.exit(1)

    log.info("Filtering %d site file(s) with keywords=%s mode=%s", len(json_files), keywords, args.mode)

    output_dir.mkdir(parents=True, exist_ok=True)
    total_matches = 0

    for path in json_files:
        result = filter_site_file(path, pattern, args.mode)
        if result is None:
            continue

        out_path = output_dir / path.name
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

        total_matches += result["match_count"]
        log.info("%s -> %d mobile URL(s) -> %s", path.name, result["match_count"], out_path)

        # quick preview in the log so you can sanity-check without opening the file
        for entry in result["mobile_urls"][:5]:
            log.info("    %s", entry["url"])
        if result["match_count"] > 5:
            log.info("    ... and %d more", result["match_count"] - 5)

    log.info("Done. %d total mobile URL(s) across %d site(s) -> %s", total_matches, len(json_files), output_dir)


if __name__ == "__main__":
    main()
