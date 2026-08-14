"""
FilterMobileUrls.py

Build the mobile-URL manifests consumed by site navigators.

The generic strategy preserves the original keyword-based behaviour for sites
whose mobile catalogue lives below a path such as ``/mobiles``.  GSMArena is
different: its phone specification pages and maker catalogues both live at the
site root.  In automatic mode this script therefore creates a two-level
GSMArena navigation manifest:

* ``tree`` / ``catalog_urls`` contain canonical maker landing pages such as
  ``xiaomi-phones-80.php``.  These are the pages a browser navigator opens.
* ``mobile_urls`` contains every directly known specification page as a
  coverage audit and fallback crawl source.

The sitemap constructor is intentionally not involved here; this script only
reads the JSON trees it has already produced.

Examples (run from the repository root):

    # Recommended: rebuild only the GSMArena manifest.
    python filestorage/FilterMobileUrls.py --site gsmarena.com

    # Preview counts and sample matches without writing anything.
    python filestorage/FilterMobileUrls.py --site gsmarena.com --dry-run

    # Preserve the original generic behaviour for all other sites.
    python filestorage/FilterMobileUrls.py

    # Force keyword matching even for GSMArena (normally not useful).
    python filestorage/FilterMobileUrls.py --site gsmarena.com --strategy keyword
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence
from urllib.parse import unquote, urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("FilterMobileUrls")

DEFAULT_INPUT_DIR = "filestorage/sitemap"
DEFAULT_OUTPUT_DIR = "filestorage/sitemap_mobile"
DEFAULT_KEYWORDS = ["mobile"]

# A GSMArena product page has a brand/model slug and a numeric phone id, for
# example ``xiaomi_redmi_note_14_4g_(global)-13616.php``.  Requiring an
# underscore separates product pages from most maker/listing pages; the deny
# markers below remove the remaining known non-spec page families.
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

# WhatMobile keeps both phone detail pages and catalogues at its root.  Detail
# pages have a brand/model underscore plus a model-name hyphen (for example
# ``Samsung_Galaxy-A57``), while brand and price catalogues end in one of the
# forms below.  This deliberately excludes StolenMobile.php, search pages and
# generic pages which the historical keyword-only manifest incorrectly kept.
WHATMOBILE_PRODUCT_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9']*_[A-Za-z0-9][A-Za-z0-9_]*-"
    r"[A-Za-z0-9][A-Za-z0-9-]*$"
)
WHATMOBILE_CATALOG_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9']*_)?(?:Mobiles_Prices|\d+_to_\d+_Mobiles)$",
    re.IGNORECASE,
)


def build_keyword_pattern(keywords: Sequence[str]) -> re.Pattern[str]:
    escaped = [re.escape(keyword.strip()) for keyword in keywords if keyword.strip()]
    if not escaped:
        raise ValueError("At least one keyword is required")
    return re.compile("|".join(escaped), re.IGNORECASE)


def canonical_site(value: str) -> str:
    """Normalize a filename/domain/base URL to a comparable site name."""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    return re.sub(r"^www\.", "", host)


def walk_nodes(node: dict) -> Iterator[dict]:
    """Yield a tree node and all descendants without recursion limits."""
    stack = [node]
    while stack:
        current = stack.pop()
        if not isinstance(current, dict):
            continue
        yield current
        children = current.get("children", [])
        if isinstance(children, list):
            stack.extend(reversed(children))


def count_urls(node: dict) -> int:
    return sum(1 for candidate in walk_nodes(node) if candidate.get("url"))


def url_path_only(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def node_matches(node: dict, pattern: re.Pattern[str]) -> bool:
    path = node.get("path") or ""
    if pattern.search(path):
        return True
    url = node.get("url") or ""
    return bool(url and pattern.search(url_path_only(url)))


def find_mobile_branches(
    node: dict,
    pattern: re.Pattern[str],
    results: List[dict],
) -> None:
    """Collect the first keyword match along each branch."""
    if node_matches(node, pattern):
        results.append(node)
        return
    for child in node.get("children", []):
        find_mobile_branches(child, pattern, results)


def find_all_matching_urls(
    node: dict,
    pattern: re.Pattern[str],
    results: List[dict],
) -> None:
    for candidate in walk_nodes(node):
        if candidate.get("url") and node_matches(candidate, pattern):
            results.append(candidate)


def domain_root(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def build_base_entry(node: dict, base_url: str, pattern: re.Pattern[str]) -> dict:
    url = node.get("url")
    inferred = False
    if not url:
        url = domain_root(base_url) + (node.get("path") or "")
        inferred = True

    match_target = node.get("path") or url_path_only(url)
    match = pattern.search(match_target)
    return {
        "url": url,
        "path": node.get("path"),
        "matched_keyword": match.group(0) if match else None,
        "url_is_inferred": inferred,
        "url_count_in_branch": count_urls(node),
    }


def build_flat_entry(node: dict, pattern: re.Pattern[str]) -> dict:
    match_target = node.get("path") or url_path_only(node["url"])
    match = pattern.search(match_target)
    return {
        "url": node["url"],
        "path": node.get("path"),
        "matched_keyword": match.group(0) if match else None,
    }


def gsmarena_product_match(url: str) -> Optional[re.Match[str]]:
    """Return the product-page regex match, or ``None`` for other URLs."""
    parsed = urlparse(url)
    if canonical_site(url) != "gsmarena.com" or parsed.query or parsed.fragment:
        return None

    filename = unquote(Path(parsed.path).name)
    match = GSMARENA_PRODUCT_FILE_RE.fullmatch(filename)
    if match is None:
        return None

    slug = match.group("slug")
    if "_" not in slug:
        return None
    if GSMARENA_NON_PRODUCT_MARKER_RE.search(filename):
        return None
    return match


def gsmarena_catalog_match(url: str) -> Optional[re.Match[str]]:
    """Match one canonical GSMArena maker landing page.

    Paginated/filter variants such as ``xiaomi-phones-f-80-0-p2.php`` are
    deliberately excluded.  The navigator discovers those from the canonical
    maker page, which keeps the stored navigation tree small and stable.
    """
    parsed = urlparse(url)
    if canonical_site(url) != "gsmarena.com" or parsed.query or parsed.fragment:
        return None
    return GSMARENA_CATALOG_FILE_RE.fullmatch(unquote(Path(parsed.path).name))


def whatmobile_product_match(url: str) -> bool:
    parsed = urlparse(url)
    return (
        canonical_site(url) == "whatmobile.com.pk"
        and not parsed.query
        and not parsed.fragment
        and bool(WHATMOBILE_PRODUCT_RE.fullmatch(unquote(Path(parsed.path).name)))
    )


def whatmobile_catalog_match(url: str) -> bool:
    parsed = urlparse(url)
    return (
        canonical_site(url) == "whatmobile.com.pk"
        and not parsed.query
        and not parsed.fragment
        and bool(WHATMOBILE_CATALOG_RE.fullmatch(unquote(Path(parsed.path).name)))
    )


def whatmobile_result(data: dict) -> dict:
    """Build clean brand/price catalogue seeds plus direct URL coverage data."""
    catalogs, products, seen_catalogs, seen_products = [], [], set(), set()
    for node in walk_nodes(data["tree"]):
        url = node.get("url")
        if not isinstance(url, str):
            continue
        if whatmobile_catalog_match(url) and url not in seen_catalogs:
            seen_catalogs.add(url)
            catalogs.append({"url": url, "path": node.get("path") or urlparse(url).path})
        elif whatmobile_product_match(url) and url not in seen_products:
            seen_products.add(url)
            products.append({"url": url, "path": node.get("path") or urlparse(url).path})
    return {
        "site": data.get("site", "whatmobile.com.pk"), "base_url": data.get("base_url"),
        "source_url_count": data.get("url_count"), "mode": "catalog_tree",
        "strategy": "whatmobile_catalog_and_product_pages", "catalog_count": len(catalogs),
        "match_count": len(products), "catalog_urls": catalogs, "mobile_urls": products,
    }


def extract_gsmarena_products(tree: dict) -> List[dict]:
    """Extract and de-duplicate GSMArena specification-page URLs."""
    products: List[dict] = []
    seen: set[str] = set()

    for node in walk_nodes(tree):
        url = node.get("url")
        if not isinstance(url, str) or url in seen:
            continue
        match = gsmarena_product_match(url)
        if match is None:
            continue
        seen.add(url)
        products.append(
            {
                "url": url,
                "path": node.get("path") or urlparse(url).path,
                "product_id": int(match.group("product_id")),
                "matched_by": "gsmarena_product_pattern",
            }
        )

    return products


def extract_gsmarena_catalogs(tree: dict) -> List[dict]:
    """Extract canonical maker pages used as browser landing points."""
    catalogs: List[dict] = []
    seen: set[str] = set()

    for node in walk_nodes(tree):
        url = node.get("url")
        if not isinstance(url, str) or url in seen:
            continue
        match = gsmarena_catalog_match(url)
        if match is None:
            continue
        seen.add(url)
        catalogs.append(
            {
                "name": match.group("maker_slug").replace("_", " "),
                "maker_slug": match.group("maker_slug"),
                "maker_id": int(match.group("maker_id")),
                "path": node.get("path") or urlparse(url).path,
                "url": url,
                "children": [],
                "matched_by": "gsmarena_maker_catalog_pattern",
            }
        )

    return catalogs


def build_gsmarena_catalog_tree(base_url: str, catalogs: Sequence[dict]) -> dict:
    """Create the filtered sitemap tree consumed by catalog navigation."""
    root_url = domain_root(base_url) + "/makers.php3"
    return {
        "name": "gsmarena.com maker catalogs",
        "path": "/makers.php3",
        "url": root_url,
        "children": [
            {
                "name": entry["name"],
                "maker_slug": entry["maker_slug"],
                "maker_id": entry["maker_id"],
                "path": entry["path"],
                "url": entry["url"],
                "children": [],
            }
            for entry in catalogs
        ],
    }


def keyword_result(
    data: dict,
    pattern: re.Pattern[str],
    mode: str,
) -> dict:
    tree = data["tree"]
    base_url = data.get("base_url", "")

    matches: List[dict] = []
    if mode == "base":
        for child in tree.get("children", []):
            find_mobile_branches(child, pattern, matches)
        entries = [build_base_entry(node, base_url, pattern) for node in matches]
    else:
        for child in tree.get("children", []):
            find_all_matching_urls(child, pattern, matches)
        entries = [build_flat_entry(node, pattern) for node in matches]

    return {
        "site": data.get("site"),
        "base_url": base_url,
        "source_url_count": data.get("url_count"),
        "mode": mode,
        "strategy": "keyword",
        "match_count": len(entries),
        "mobile_urls": entries,
    }


def gsmarena_result(data: dict) -> dict:
    catalogs = extract_gsmarena_catalogs(data["tree"])
    products = extract_gsmarena_products(data["tree"])
    base_url = data.get("base_url", "https://www.gsmarena.com")
    return {
        "site": data.get("site", "gsmarena.com"),
        "base_url": base_url,
        "source_url_count": data.get("url_count"),
        "mode": "catalog_tree",
        "strategy": "gsmarena_catalog_and_product_pages",
        "catalog_count": len(catalogs),
        "match_count": len(products),
        "tree": build_gsmarena_catalog_tree(base_url, catalogs),
        "catalog_urls": catalogs,
        "mobile_urls": products,
    }


def load_tree_file(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Could not read %s: %s", path, exc)
        return None

    if not isinstance(data, dict) or not isinstance(data.get("tree"), dict):
        log.error("%s does not contain a valid 'tree' object", path)
        return None
    return data


def filter_site_file(
    path: Path,
    pattern: re.Pattern[str],
    mode: str,
    strategy: str = "auto",
) -> Optional[dict]:
    data = load_tree_file(path)
    if data is None:
        return None

    site = canonical_site(str(data.get("site") or path.stem))
    resolved_strategy = strategy
    if strategy == "auto":
        resolved_strategy = (
            "gsmarena-catalog" if site == "gsmarena.com" else
            "whatmobile-catalog" if site == "whatmobile.com.pk" else "keyword"
        )

    if resolved_strategy in {"gsmarena-catalog", "gsmarena-products"}:
        if site != "gsmarena.com":
            log.error("GSMArena product strategy cannot process site %s", site)
            return None
        return gsmarena_result(data)
    if resolved_strategy == "whatmobile-catalog":
        if site != "whatmobile.com.pk":
            log.error("WhatMobile catalogue strategy cannot process site %s", site)
            return None
        return whatmobile_result(data)
    return keyword_result(data, pattern, mode)


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def select_input_files(input_dir: Path, sites: Sequence[str]) -> List[Path]:
    if not sites:
        return sorted(input_dir.glob("*.json"))

    selected: List[Path] = []
    for requested in sites:
        site = canonical_site(requested)
        candidate = input_dir / f"{site}.json"
        if candidate.exists():
            selected.append(candidate)
        else:
            log.error("Site tree not found: %s", candidate)
    return selected


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Filter sitemap trees into mobile URL manifests."
    )
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--site",
        action="append",
        default=[],
        help="Process only this site (repeatable), e.g. --site gsmarena.com",
    )
    parser.add_argument(
        "--strategy",
        choices=["auto", "keyword", "gsmarena-catalog", "gsmarena-products", "whatmobile-catalog"],
        default="auto",
        help="'auto' creates a maker-catalog tree plus product fallback for GSMArena.",
    )
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help="Comma-separated path keywords for the generic strategy.",
    )
    parser.add_argument(
        "--mode",
        choices=["base", "all"],
        default="base",
        help="Generic keyword mode; the GSMArena combined strategy ignores it.",
    )
    parser.add_argument(
        "--sample",
        type=positive_int,
        default=5,
        help="Number of matched URLs to show in the log.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect counts and samples without writing output files.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.is_dir():
        log.error("Input directory not found: %s", input_dir)
        return 2

    keywords = [item.strip() for item in args.keywords.split(",") if item.strip()]
    try:
        pattern = build_keyword_pattern(keywords)
    except ValueError as exc:
        log.error("%s", exc)
        return 2

    json_files = select_input_files(input_dir, args.site)
    if not json_files:
        log.error("No matching JSON site trees found in %s", input_dir)
        return 2

    total_matches = 0
    successful_files = 0
    for path in json_files:
        result = filter_site_file(path, pattern, args.mode, args.strategy)
        if result is None:
            continue

        successful_files += 1
        total_matches += result["match_count"]
        if result.get("strategy") == "gsmarena_catalog_and_product_pages":
            log.info(
                "%s: strategy=%s, catalogs=%d, products=%d of source=%s",
                path.name,
                result["strategy"],
                result["catalog_count"],
                result["match_count"],
                result.get("source_url_count"),
            )
            log.info("    Catalog landing-page sample:")
            for entry in result["catalog_urls"][: args.sample]:
                log.info("      %s", entry["url"])
            log.info("    Direct product fallback sample:")
            for entry in result["mobile_urls"][: args.sample]:
                log.info("      %s", entry["url"])
        else:
            log.info(
                "%s: strategy=%s, matched=%d of source=%s",
                path.name,
                result["strategy"],
                result["match_count"],
                result.get("source_url_count"),
            )
            for entry in result["mobile_urls"][: args.sample]:
                log.info("    %s", entry["url"])

        if not args.dry_run:
            out_path = output_dir / path.name
            atomic_write_json(out_path, result)
            log.info("Saved %s", out_path)

    if successful_files == 0:
        return 1

    action = "Would write" if args.dry_run else "Wrote"
    log.info(
        "%s %d manifest(s) containing %d matched URL(s)",
        action,
        successful_files,
        total_matches,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
