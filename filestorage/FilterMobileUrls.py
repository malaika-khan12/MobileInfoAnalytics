"""
FilterMobileUrls.py

Build the mobile-URL manifests consumed by site navigators.

Site-specific strategies:

- Generic sites:
    keyword matching

- GSMArena:
    maker catalogues + direct product pages

- WhatMobile:
    catalogue pages + direct product pages

- WhatAMobile:
    direct /product/ pages

- Mega.pk:
    direct /mobiles_products/<id>/<slug>.html pages
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Sequence
from urllib.parse import urlparse


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("FilterMobileUrls")


DEFAULT_INPUT_DIR = "filestorage/sitemap"
DEFAULT_OUTPUT_DIR = "filestorage/sitemap_mobile"
DEFAULT_KEYWORDS = ["mobile"]


# ============================================================================
# GSMARENA
# ============================================================================

GSMARENA_PRODUCT_FILE_RE = re.compile(
    r"^(?P<slug>[a-z0-9][a-z0-9_()+.,%'-]*)-"
    r"(?P<product_id>[0-9]+)\.php$",
    re.IGNORECASE,
)

GSMARENA_NON_PRODUCT_MARKER_RE = re.compile(
    r"-(?:phones?|reviews?|pictures?|opinions?|prices?|videos?|"
    r"related|compare|news)-",
    re.IGNORECASE,
)

GSMARENA_CATALOG_FILE_RE = re.compile(
    r"^(?P<maker_slug>[a-z0-9][a-z0-9_()+.,%'-]*)-phones-"
    r"(?P<maker_id>[0-9]+)\.php$",
    re.IGNORECASE,
)


# ============================================================================
# WHATMOBILE
# ============================================================================

WHATMOBILE_PRODUCT_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9']*_[A-Za-z0-9][A-Za-z0-9_]*-"
    r"[A-Za-z0-9][A-Za-z0-9-]*$"
)

WHATMOBILE_CATALOG_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9']*_)?"
    r"(?:Mobiles_Prices|\d+_to_\d+_Mobiles)$",
    re.IGNORECASE,
)


# ============================================================================
# WHATAMOBILE
# ============================================================================

WHATAMOBILE_PRODUCT_PATH_RE = re.compile(
    r"^/product/[^/?#]+/?$",
    re.IGNORECASE,
)

WHATAMOBILE_CATALOG_PATH_RE = re.compile(
    r"^/product-cat/mobiles(?:/page/\d+)?/?$",
    re.IGNORECASE,
)


# ============================================================================
# MEGA.PK
# ============================================================================

MEGA_PRODUCT_PATH_RE = re.compile(
    r"^/mobiles_products/"
    r"\d+/"
    r"[^/?#]+\.html/?$",
    re.IGNORECASE,
)

MEGA_CATALOG_PATH_RE = re.compile(
    r"^/mobiles(?:/\d+)?/?$",
    re.IGNORECASE,
)


# ============================================================================
# GENERIC HELPERS
# ============================================================================

def build_keyword_pattern(
    keywords: Sequence[str],
) -> re.Pattern[str]:

    escaped = [
        re.escape(keyword.strip())
        for keyword in keywords
        if keyword.strip()
    ]

    if not escaped:
        raise ValueError(
            "At least one keyword is required"
        )

    return re.compile(
        "|".join(escaped),
        re.IGNORECASE,
    )


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


def walk_nodes(
    node: dict,
) -> Iterator[dict]:

    stack = [node]

    while stack:

        current = stack.pop()

        if not isinstance(
            current,
            dict,
        ):
            continue

        yield current

        children = current.get(
            "children",
            [],
        )

        if isinstance(
            children,
            list,
        ):
            stack.extend(
                reversed(children)
            )


def count_urls(
    node: dict,
) -> int:

    return sum(
        1
        for candidate in walk_nodes(node)
        if candidate.get("url")
    )


def url_path_only(
    url: str,
) -> str:

    parsed = urlparse(url)

    return (
        parsed.path
        + (
            f"?{parsed.query}"
            if parsed.query
            else ""
        )
    )


def node_matches(
    node: dict,
    pattern: re.Pattern[str],
) -> bool:

    path = node.get(
        "path"
    ) or ""

    if pattern.search(path):
        return True

    url = node.get(
        "url"
    ) or ""

    return bool(
        url
        and pattern.search(
            url_path_only(url)
        )
    )


def find_mobile_branches(
    node: dict,
    pattern: re.Pattern[str],
    results: List[dict],
) -> None:

    if node_matches(
        node,
        pattern,
    ):
        results.append(node)
        return

    for child in node.get(
        "children",
        [],
    ):
        find_mobile_branches(
            child,
            pattern,
            results,
        )


def find_all_matching_urls(
    node: dict,
    pattern: re.Pattern[str],
    results: List[dict],
) -> None:

    for candidate in walk_nodes(node):

        if (
            candidate.get("url")
            and node_matches(
                candidate,
                pattern,
            )
        ):
            results.append(candidate)


def domain_root(
    base_url: str,
) -> str:

    parsed = urlparse(base_url)

    return (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
    )


def build_base_entry(
    node: dict,
    base_url: str,
    pattern: re.Pattern[str],
) -> dict:

    url = node.get("url")
    inferred = False

    if not url:

        url = (
            domain_root(base_url)
            + (
                node.get("path")
                or ""
            )
        )

        inferred = True

    match_target = (
        node.get("path")
        or url_path_only(url)
    )

    match = pattern.search(
        match_target
    )

    return {
        "url": url,
        "path": node.get("path"),
        "matched_keyword": (
            match.group(0)
            if match
            else None
        ),
        "url_is_inferred": inferred,
        "url_count_in_branch": (
            count_urls(node)
        ),
    }


def build_flat_entry(
    node: dict,
    pattern: re.Pattern[str],
) -> dict:

    match_target = (
        node.get("path")
        or url_path_only(
            node["url"]
        )
    )

    match = pattern.search(
        match_target
    )

    return {
        "url": node["url"],
        "path": node.get("path"),
        "matched_keyword": (
            match.group(0)
            if match
            else None
        ),
    }


# ============================================================================
# GSMARENA MATCHERS
# ============================================================================

def gsmarena_product_match(
    url: str,
) -> Optional[re.Match[str]]:

    parsed = urlparse(url)

    if (
        canonical_site(url)
        != "gsmarena.com"
        or parsed.query
        or parsed.fragment
    ):
        return None

    filename = Path(
        parsed.path
    ).name

    match = GSMARENA_PRODUCT_FILE_RE.fullmatch(
        filename
    )

    if match is None:
        return None

    if "_" not in match.group(
        "slug"
    ):
        return None

    if GSMARENA_NON_PRODUCT_MARKER_RE.search(
        filename
    ):
        return None

    return match


def gsmarena_catalog_match(
    url: str,
) -> Optional[re.Match[str]]:

    parsed = urlparse(url)

    if (
        canonical_site(url)
        != "gsmarena.com"
        or parsed.query
        or parsed.fragment
    ):
        return None

    return GSMARENA_CATALOG_FILE_RE.fullmatch(
        Path(parsed.path).name
    )


# ============================================================================
# WHATMOBILE MATCHERS
# ============================================================================

def whatmobile_product_match(
    url: str,
) -> bool:

    parsed = urlparse(url)

    return (
        canonical_site(url)
        == "whatmobile.com.pk"
        and not parsed.query
        and not parsed.fragment
        and bool(
            WHATMOBILE_PRODUCT_RE.fullmatch(
                Path(parsed.path).name
            )
        )
    )


def whatmobile_catalog_match(
    url: str,
) -> bool:

    parsed = urlparse(url)

    return (
        canonical_site(url)
        == "whatmobile.com.pk"
        and not parsed.query
        and not parsed.fragment
        and bool(
            WHATMOBILE_CATALOG_RE.fullmatch(
                Path(parsed.path).name
            )
        )
    )


# ============================================================================
# WHATAMOBILE MATCHERS
# ============================================================================

def whatamobile_product_match(
    url: str,
) -> bool:

    parsed = urlparse(url)

    if (
        canonical_site(url)
        != "whatamobile.com.pk"
    ):
        return False

    if (
        parsed.query
        or parsed.fragment
    ):
        return False

    return bool(
        WHATAMOBILE_PRODUCT_PATH_RE.fullmatch(
            parsed.path
        )
    )


def whatamobile_catalog_match(
    url: str,
) -> bool:

    parsed = urlparse(url)

    if (
        canonical_site(url)
        != "whatamobile.com.pk"
    ):
        return False

    if (
        parsed.query
        or parsed.fragment
    ):
        return False

    return bool(
        WHATAMOBILE_CATALOG_PATH_RE.fullmatch(
            parsed.path
        )
    )


# ============================================================================
# MEGA MATCHERS
# ============================================================================

def mega_product_match(
    url: str,
) -> bool:
    """
    Match only individual Mega.pk mobile product pages.

    Example:

        /mobiles_products/27057/
        Samsung-Galaxy-A57-...html
    """

    parsed = urlparse(url)

    if (
        canonical_site(url)
        not in {
            "mega.pk",
        }
    ):
        return False

    if (
        parsed.query
        or parsed.fragment
    ):
        return False

    return bool(
        MEGA_PRODUCT_PATH_RE.fullmatch(
            parsed.path
        )
    )


def mega_catalog_match(
    url: str,
) -> bool:

    parsed = urlparse(url)

    if (
        canonical_site(url)
        != "mega.pk"
    ):
        return False

    if (
        parsed.query
        or parsed.fragment
    ):
        return False

    return bool(
        MEGA_CATALOG_PATH_RE.fullmatch(
            parsed.path
        )
    )


# ============================================================================
# WHATMOBILE RESULT
# ============================================================================

def whatmobile_result(
    data: dict,
) -> dict:

    catalogs = []
    products = []

    seen_catalogs = set()
    seen_products = set()

    for node in walk_nodes(
        data["tree"]
    ):

        url = node.get("url")

        if not isinstance(
            url,
            str,
        ):
            continue

        if (
            whatmobile_catalog_match(url)
            and url not in seen_catalogs
        ):

            seen_catalogs.add(url)

            catalogs.append(
                {
                    "url": url,
                    "path": (
                        node.get("path")
                        or urlparse(
                            url
                        ).path
                    ),
                }
            )

        elif (
            whatmobile_product_match(url)
            and url not in seen_products
        ):

            seen_products.add(url)

            products.append(
                {
                    "url": url,
                    "path": (
                        node.get("path")
                        or urlparse(
                            url
                        ).path
                    ),
                }
            )

    return {
        "site": data.get(
            "site",
            "whatmobile.com.pk",
        ),
        "base_url": data.get(
            "base_url"
        ),
        "source_url_count": data.get(
            "url_count"
        ),
        "mode": "catalog_tree",
        "strategy": (
            "whatmobile_catalog_and_product_pages"
        ),
        "catalog_count": len(
            catalogs
        ),
        "match_count": len(
            products
        ),
        "catalog_urls": catalogs,
        "mobile_urls": products,
    }


# ============================================================================
# WHATAMOBILE RESULT
# ============================================================================

def extract_whatamobile_products(
    tree: dict,
) -> List[dict]:

    products: List[dict] = []
    seen: set[str] = set()

    for node in walk_nodes(
        tree
    ):

        url = node.get("url")

        if not isinstance(
            url,
            str,
        ):
            continue

        if url in seen:
            continue

        if not whatamobile_product_match(
            url
        ):
            continue

        seen.add(url)

        products.append(
            {
                "url": url,
                "path": (
                    node.get("path")
                    or urlparse(
                        url
                    ).path
                ),
                "matched_by": (
                    "whatamobile_product_path"
                ),
            }
        )

    return products


def extract_whatamobile_catalogs(
    tree: dict,
) -> List[dict]:

    catalogs: List[dict] = []
    seen: set[str] = set()

    for node in walk_nodes(
        tree
    ):

        url = node.get("url")

        if not isinstance(
            url,
            str,
        ):
            continue

        if url in seen:
            continue

        if not whatamobile_catalog_match(
            url
        ):
            continue

        seen.add(url)

        catalogs.append(
            {
                "path": (
                    node.get("path")
                    or urlparse(
                        url
                    ).path
                ),
                "url": url,
                "matched_by": (
                    "whatamobile_catalog_path"
                ),
            }
        )

    return catalogs


def whatamobile_result(
    data: dict,
) -> dict:

    products = extract_whatamobile_products(
        data["tree"]
    )

    catalogs = extract_whatamobile_catalogs(
        data["tree"]
    )

    base_url = data.get(
        "base_url",
        "https://www.whatamobile.com.pk",
    )

    return {
        "site": data.get(
            "site",
            "whatamobile.com.pk",
        ),
        "base_url": base_url,
        "source_url_count": data.get(
            "url_count"
        ),
        "mode": "direct_products",
        "strategy": (
            "whatamobile_product_path"
        ),
        "catalog_count": len(
            catalogs
        ),
        "catalog_urls": catalogs,
        "match_count": len(
            products
        ),
        "mobile_urls": products,
    }


# ============================================================================
# MEGA RESULT
# ============================================================================

def extract_mega_products(
    tree: dict,
) -> List[dict]:
    """
    Extract direct Mega.pk mobile product URLs.

    Only /mobiles_products/<id>/<slug>.html is accepted.
    """

    products: List[dict] = []

    seen: set[str] = set()

    for node in walk_nodes(
        tree
    ):

        url = node.get("url")

        if not isinstance(
            url,
            str,
        ):
            continue

        if url in seen:
            continue

        if not mega_product_match(
            url
        ):
            continue

        seen.add(url)

        parsed = urlparse(url)

        product_match = re.search(
            r"/mobiles_products/(\d+)/",
            parsed.path,
            re.IGNORECASE,
        )

        product_id = (
            int(product_match.group(1))
            if product_match
            else None
        )

        products.append(
            {
                "url": url,
                "path": (
                    node.get("path")
                    or parsed.path
                ),
                "product_id": product_id,
                "matched_by": (
                    "mega_mobile_product_path"
                ),
            }
        )

    return products


def extract_mega_catalogs(
    tree: dict,
) -> List[dict]:

    catalogs: List[dict] = []

    seen: set[str] = set()

    for node in walk_nodes(
        tree
    ):

        url = node.get("url")

        if not isinstance(
            url,
            str,
        ):
            continue

        if url in seen:
            continue

        if not mega_catalog_match(
            url
        ):
            continue

        seen.add(url)

        catalogs.append(
            {
                "url": url,
                "path": (
                    node.get("path")
                    or urlparse(
                        url
                    ).path
                ),
                "matched_by": (
                    "mega_mobile_catalog_path"
                ),
            }
        )

    return catalogs


def mega_result(
    data: dict,
) -> dict:
    """
    Build Mega.pk direct-product manifest.

    This intentionally excludes:
        /mobiles/comparison/
        /mobiles/
        /brand/
        /product/
        accessories
        non-mobile product sections
    """

    products = extract_mega_products(
        data["tree"]
    )

    catalogs = extract_mega_catalogs(
        data["tree"]
    )

    base_url = data.get(
        "base_url",
        "https://www.mega.pk",
    )

    return {
        "site": data.get(
            "site",
            "mega.pk",
        ),
        "base_url": base_url,
        "source_url_count": data.get(
            "url_count"
        ),
        "mode": "direct_products",
        "strategy": "mega_mobile_product_path",
        "catalog_count": len(
            catalogs
        ),
        "match_count": len(
            products
        ),
        "catalog_urls": catalogs,
        "mobile_urls": products,
    }


# ============================================================================
# GSMARENA RESULT
# ============================================================================

def extract_gsmarena_products(
    tree: dict,
) -> List[dict]:

    products: List[dict] = []
    seen: set[str] = set()

    for node in walk_nodes(
        tree
    ):

        url = node.get("url")

        if not isinstance(
            url,
            str,
        ):
            continue

        if url in seen:
            continue

        match = gsmarena_product_match(
            url
        )

        if match is None:
            continue

        seen.add(url)

        products.append(
            {
                "url": url,
                "path": (
                    node.get("path")
                    or urlparse(
                        url
                    ).path
                ),
                "product_id": int(
                    match.group(
                        "product_id"
                    )
                ),
                "matched_by": (
                    "gsmarena_product_pattern"
                ),
            }
        )

    return products


def extract_gsmarena_catalogs(
    tree: dict,
) -> List[dict]:

    catalogs: List[dict] = []
    seen: set[str] = set()

    for node in walk_nodes(
        tree
    ):

        url = node.get("url")

        if not isinstance(
            url,
            str,
        ):
            continue

        if url in seen:
            continue

        match = gsmarena_catalog_match(
            url
        )

        if match is None:
            continue

        seen.add(url)

        catalogs.append(
            {
                "name": (
                    match.group(
                        "maker_slug"
                    ).replace(
                        "_",
                        " ",
                    )
                ),
                "maker_slug": (
                    match.group(
                        "maker_slug"
                    )
                ),
                "maker_id": int(
                    match.group(
                        "maker_id"
                    )
                ),
                "path": (
                    node.get("path")
                    or urlparse(
                        url
                    ).path
                ),
                "url": url,
                "children": [],
                "matched_by": (
                    "gsmarena_maker_catalog_pattern"
                ),
            }
        )

    return catalogs


def build_gsmarena_catalog_tree(
    base_url: str,
    catalogs: Sequence[dict],
) -> dict:

    root_url = (
        domain_root(base_url)
        + "/makers.php3"
    )

    return {
        "name": (
            "gsmarena.com maker catalogs"
        ),
        "path": "/makers.php3",
        "url": root_url,
        "children": [
            {
                "name": entry["name"],
                "maker_slug": (
                    entry["maker_slug"]
                ),
                "maker_id": (
                    entry["maker_id"]
                ),
                "path": entry["path"],
                "url": entry["url"],
                "children": [],
            }
            for entry in catalogs
        ],
    }


def gsmarena_result(
    data: dict,
) -> dict:

    catalogs = extract_gsmarena_catalogs(
        data["tree"]
    )

    products = extract_gsmarena_products(
        data["tree"]
    )

    base_url = data.get(
        "base_url",
        "https://www.gsmarena.com",
    )

    return {
        "site": data.get(
            "site",
            "gsmarena.com",
        ),
        "base_url": base_url,
        "source_url_count": data.get(
            "url_count"
        ),
        "mode": "catalog_tree",
        "strategy": (
            "gsmarena_catalog_and_product_pages"
        ),
        "catalog_count": len(
            catalogs
        ),
        "match_count": len(
            products
        ),
        "tree": build_gsmarena_catalog_tree(
            base_url,
            catalogs,
        ),
        "catalog_urls": catalogs,
        "mobile_urls": products,
    }


# ============================================================================
# GENERIC RESULT
# ============================================================================

def keyword_result(
    data: dict,
    pattern: re.Pattern[str],
    mode: str,
) -> dict:

    tree = data["tree"]

    base_url = data.get(
        "base_url",
        "",
    )

    matches: List[dict] = []

    if mode == "base":

        for child in tree.get(
            "children",
            [],
        ):

            find_mobile_branches(
                child,
                pattern,
                matches,
            )

        entries = [
            build_base_entry(
                node,
                base_url,
                pattern,
            )
            for node in matches
        ]

    else:

        for child in tree.get(
            "children",
            [],
        ):

            find_all_matching_urls(
                child,
                pattern,
                matches,
            )

        entries = [
            build_flat_entry(
                node,
                pattern,
            )
            for node in matches
        ]

    return {
        "site": data.get(
            "site"
        ),
        "base_url": base_url,
        "source_url_count": data.get(
            "url_count"
        ),
        "mode": mode,
        "strategy": "keyword",
        "match_count": len(
            entries
        ),
        "mobile_urls": entries,
    }


# ============================================================================
# INPUT
# ============================================================================

def load_tree_file(
    path: Path,
) -> Optional[dict]:

    try:

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except (
        json.JSONDecodeError,
        OSError,
    ) as exc:

        log.error(
            "Could not read %s: %s",
            path,
            exc,
        )

        return None

    if (
        not isinstance(
            data,
            dict,
        )
        or not isinstance(
            data.get("tree"),
            dict,
        )
    ):

        log.error(
            "%s does not contain a valid "
            "'tree' object",
            path,
        )

        return None

    return data


def filter_site_file(
    path: Path,
    pattern: re.Pattern[str],
    mode: str,
    strategy: str = "auto",
) -> Optional[dict]:

    data = load_tree_file(
        path
    )

    if data is None:
        return None

    site = canonical_site(
        str(
            data.get(
                "site"
            )
            or path.stem
        )
    )

    resolved_strategy = strategy

    if strategy == "auto":

        if site == "gsmarena.com":

            resolved_strategy = (
                "gsmarena-catalog"
            )

        elif site == "whatmobile.com.pk":

            resolved_strategy = (
                "whatmobile-catalog"
            )

        elif site == "whatamobile.com.pk":

            resolved_strategy = (
                "whatamobile-products"
            )

        elif site == "mega.pk":

            resolved_strategy = (
                "mega-products"
            )

        else:

            resolved_strategy = (
                "keyword"
            )

    if resolved_strategy in {
        "gsmarena-catalog",
        "gsmarena-products",
    }:

        if site != "gsmarena.com":

            log.error(
                "GSMArena strategy cannot "
                "process site %s",
                site,
            )

            return None

        return gsmarena_result(
            data
        )

    if resolved_strategy == (
        "whatmobile-catalog"
    ):

        if site != (
            "whatmobile.com.pk"
        ):

            log.error(
                "WhatMobile strategy cannot "
                "process site %s",
                site,
            )

            return None

        return whatmobile_result(
            data
        )

    if resolved_strategy == (
        "whatamobile-products"
    ):

        if site != (
            "whatamobile.com.pk"
        ):

            log.error(
                "WhatAMobile strategy cannot "
                "process site %s",
                site,
            )

            return None

        return whatamobile_result(
            data
        )

    if resolved_strategy == (
        "mega-products"
    ):

        if site != "mega.pk":

            log.error(
                "Mega strategy cannot "
                "process site %s",
                site,
            )

            return None

        return mega_result(
            data
        )

    return keyword_result(
        data,
        pattern,
        mode,
    )


# ============================================================================
# WRITE
# ============================================================================

def atomic_write_json(
    path: Path,
    payload: dict,
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_name(
        path.name + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(
        path
    )


# ============================================================================
# INPUT FILE SELECTION
# ============================================================================

def select_input_files(
    input_dir: Path,
    sites: Sequence[str],
) -> List[Path]:

    if not sites:

        return sorted(
            input_dir.glob(
                "*.json"
            )
        )

    selected: List[Path] = []

    for requested in sites:

        site = canonical_site(
            requested
        )

        candidate = (
            input_dir
            / f"{site}.json"
        )

        if candidate.exists():

            selected.append(
                candidate
            )

        else:

            log.error(
                "Site tree not found: %s",
                candidate,
            )

    return selected


# ============================================================================
# CLI
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


def build_parser():

    parser = argparse.ArgumentParser(
        description=(
            "Filter sitemap trees into "
            "mobile URL manifests."
        )
    )

    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
    )

    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
    )

    parser.add_argument(
        "--site",
        action="append",
        default=[],
        help=(
            "Process only this site. Repeatable."
        ),
    )

    parser.add_argument(
        "--strategy",
        choices=[
            "auto",
            "keyword",
            "gsmarena-catalog",
            "gsmarena-products",
            "whatmobile-catalog",
            "whatamobile-products",
            "mega-products",
        ],
        default="auto",
    )

    parser.add_argument(
        "--keywords",
        default=",".join(
            DEFAULT_KEYWORDS
        ),
    )

    parser.add_argument(
        "--mode",
        choices=[
            "base",
            "all",
        ],
        default="base",
    )

    parser.add_argument(
        "--sample",
        type=positive_int,
        default=5,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    return parser


# ============================================================================
# MAIN
# ============================================================================

def main(
    argv: Optional[Sequence[str]] = None,
) -> int:

    args = build_parser().parse_args(
        argv
    )

    input_dir = Path(
        args.input_dir
    )

    output_dir = Path(
        args.output_dir
    )

    if not input_dir.is_dir():

        log.error(
            "Input directory not found: %s",
            input_dir,
        )

        return 2

    keywords = [
        item.strip()
        for item in args.keywords.split(",")
        if item.strip()
    ]

    try:

        pattern = (
            build_keyword_pattern(
                keywords
            )
        )

    except ValueError as exc:

        log.error(
            "%s",
            exc,
        )

        return 2

    json_files = (
        select_input_files(
            input_dir,
            args.site,
        )
    )

    if not json_files:

        log.error(
            "No matching JSON site trees "
            "found in %s",
            input_dir,
        )

        return 2

    total_matches = 0
    successful_files = 0

    for path in json_files:

        result = filter_site_file(
            path,
            pattern,
            args.mode,
            args.strategy,
        )

        if result is None:
            continue

        successful_files += 1

        total_matches += result[
            "match_count"
        ]

        strategy_name = result.get(
            "strategy"
        )

        # --------------------------------------------------------------
        # Mega
        # --------------------------------------------------------------

        if strategy_name == (
            "mega_mobile_product_path"
        ):

            log.info(
                "%s: strategy=%s, "
                "products=%d of source=%s",
                path.name,
                strategy_name,
                result[
                    "match_count"
                ],
                result.get(
                    "source_url_count"
                ),
            )

            log.info(
                "    Catalog URLs found: %d",
                result.get(
                    "catalog_count",
                    0,
                ),
            )

            log.info(
                "    Product sample:"
            )

            for entry in result[
                "mobile_urls"
            ][: args.sample]:

                log.info(
                    "      %s",
                    entry["url"],
                )

        # --------------------------------------------------------------
        # WhatAMobile
        # --------------------------------------------------------------

        elif strategy_name == (
            "whatamobile_product_path"
        ):

            log.info(
                "%s: strategy=%s, "
                "products=%d of source=%s",
                path.name,
                strategy_name,
                result[
                    "match_count"
                ],
                result.get(
                    "source_url_count"
                ),
            )

            log.info(
                "    Product sample:"
            )

            for entry in result[
                "mobile_urls"
            ][: args.sample]:

                log.info(
                    "      %s",
                    entry["url"],
                )

        # --------------------------------------------------------------
        # GSMArena
        # --------------------------------------------------------------

        elif strategy_name == (
            "gsmarena_catalog_and_product_pages"
        ):

            log.info(
                "%s: strategy=%s, "
                "catalogs=%d, products=%d "
                "of source=%s",
                path.name,
                strategy_name,
                result[
                    "catalog_count"
                ],
                result[
                    "match_count"
                ],
                result.get(
                    "source_url_count"
                ),
            )

        # --------------------------------------------------------------
        # WhatMobile
        # --------------------------------------------------------------

        elif strategy_name == (
            "whatmobile_catalog_and_product_pages"
        ):

            log.info(
                "%s: strategy=%s, "
                "catalogs=%d, products=%d "
                "of source=%s",
                path.name,
                strategy_name,
                result[
                    "catalog_count"
                ],
                result[
                    "match_count"
                ],
                result.get(
                    "source_url_count"
                ),
            )

        # --------------------------------------------------------------
        # Generic
        # --------------------------------------------------------------

        else:

            log.info(
                "%s: strategy=%s, "
                "matched=%d of source=%s",
                path.name,
                strategy_name,
                result[
                    "match_count"
                ],
                result.get(
                    "source_url_count"
                ),
            )

        # --------------------------------------------------------------
        # Write
        # --------------------------------------------------------------

        if not args.dry_run:

            out_path = (
                output_dir
                / path.name
            )

            atomic_write_json(
                out_path,
                result,
            )

            log.info(
                "Saved %s",
                out_path,
            )

    if successful_files == 0:
        return 1

    action = (
        "Would write"
        if args.dry_run
        else "Wrote"
    )

    log.info(
        "%s %d manifest(s) containing "
        "%d matched URL(s)",
        action,
        successful_files,
        total_matches,
    )

    return 0


if __name__ == "__main__":
    sys.exit(
        main()
    )