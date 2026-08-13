# Site Tree JSON Format & `treeConstructor.py`

This document describes the input file format, the sitemap discovery
process, and the JSON tree structure that `filestorage/treeConstructor.py`
produces for each site.

---

## 1. Input: `site-list.txt`

Sites to process are listed under section headers. Each header line ends
with a colon and is followed by one URL per line:

```
MAIN_SITE:
https://www.gsmarena.com
SITES:
https://www.whatmobile.com.pk/
https://www.daraz.pk/
...
UNAUTHORIZED_SITES:
https://qeemat.com.pk/
...
```

| Section | Behavior |
|---|---|
| `MAIN_SITE:` | Processed like any other site. |
| `SITES:` | Processed normally. |
| `UNAUTHORIZED_SITES:` | **Always skipped.** No requests are ever made to these hosts. |

Blank lines are ignored. Any line under a section that isn't a URL
(doesn't start with `http://` or `https://`) is ignored with a warning.

---

## 2. Output: `filestorage/sitemap/<sitename>.json`

One JSON file is written per authorized site. The filename is the site's
domain with `www.` stripped, e.g. `https://www.priceoye.pk/` →
`priceoye.pk.json`.

### Top-level shape

```json
{
  "site": "priceoye.pk",
  "base_url": "https://priceoye.pk/mobiles/",
  "url_count": 9,
  "tree": { ...TreeNode... }
}
```

| Field | Type | Meaning |
|---|---|---|
| `site` | string | Sanitized domain name, used as the output filename stem. |
| `base_url` | string | The URL from `site-list.txt` this site was crawled from. |
| `url_count` | integer | Total number of distinct URLs found across all of that site's sitemap(s). |
| `tree` | `TreeNode` | The root of the site's URL tree (see below). |

### `TreeNode` shape

Every node — root, folder, or page — has the same four fields:

```json
{
  "name": "mobiles",
  "path": "/mobiles",
  "url": "https://priceoye.pk/mobiles",
  "children": [ ...TreeNode... ]
}
```

| Field | Type | Meaning |
|---|---|---|
| `name` | string | This node's own path segment (e.g. `"mobiles"`, `"galaxy-s24"`). The root node's `name` is the site's domain. |
| `path` | string | Full site-relative path from the root down to this node, e.g. `"/mobiles/samsung/galaxy-s24"`. The root's path is `"/"`. |
| `url` | string \| `null` | The actual page URL, **only if that exact path appeared in the site's sitemap**. `null` if this segment only exists because a deeper URL passed through it (a "folder" that was never itself a listed page). |
| `children` | `TreeNode[]` | Nested nodes for each next path segment. Empty array `[]` for leaf pages. |

### Example

Sitemap URLs:
```
https://priceoye.pk/mobiles
https://priceoye.pk/mobiles/samsung/galaxy-s24
https://priceoye.pk/mobiles/apple-iphone-15
https://priceoye.pk/mobiles/apple-iphone-15/reviews
https://priceoye.pk/garments/mens
```

Produces:

```json
{
  "site": "priceoye.pk",
  "base_url": "https://priceoye.pk/mobiles/",
  "url_count": 5,
  "tree": {
    "name": "priceoye.pk",
    "path": "/",
    "url": null,
    "children": [
      {
        "name": "mobiles",
        "path": "/mobiles",
        "url": "https://priceoye.pk/mobiles",
        "children": [
          {
            "name": "samsung",
            "path": "/mobiles/samsung",
            "url": null,
            "children": [
              {
                "name": "galaxy-s24",
                "path": "/mobiles/samsung/galaxy-s24",
                "url": "https://priceoye.pk/mobiles/samsung/galaxy-s24",
                "children": []
              }
            ]
          },
          {
            "name": "apple-iphone-15",
            "path": "/mobiles/apple-iphone-15",
            "url": "https://priceoye.pk/mobiles/apple-iphone-15",
            "children": [
              {
                "name": "reviews",
                "path": "/mobiles/apple-iphone-15/reviews",
                "url": "https://priceoye.pk/mobiles/apple-iphone-15/reviews",
                "children": []
              }
            ]
          }
        ]
      },
      {
        "name": "garments",
        "path": "/garments",
        "url": null,
        "children": [
          {
            "name": "mens",
            "path": "/garments/mens",
            "url": "https://priceoye.pk/garments/mens",
            "children": []
          }
        ]
      }
    ]
  }
}
```

Notice `samsung` has `"url": null` — it's only a folder in the tree
because `galaxy-s24` sits underneath it; `/mobiles/samsung` itself was
never a page in the sitemap.

---

## 3. How `treeConstructor.py` builds this

For each authorized site:

1. **Discover the sitemap.**
   - Fetch `/robots.txt` and read every `Sitemap:` line.
   - If none are listed, fall back to trying common paths in order:
     `/sitemap.xml`, `/sitemap_index.xml`, `/sitemap-index.xml`,
     `/sitemap/sitemap.xml`, `/wp-sitemap.xml`.

2. **Download and parse the sitemap.**
   - If the root element is `<sitemapindex>` (a sitemap that just lists
     other sitemaps — common on large sites), each child sitemap is
     fetched and parsed recursively, up to a depth guard
     (`MAX_SITEMAP_DEPTH = 5`) to prevent infinite loops.
   - If the root element is `<urlset>`, every `<loc>` is collected.
   - `.xml.gz` sitemaps are decompressed automatically.
   - A hard cap (`MAX_URLS_PER_SITE = 200,000`) stops collection from
     growing unbounded on very large sites (e.g. daraz.pk, gsmarena.com).

3. **Build the tree.**
   - Every collected URL's path is split into segments
     (`/mobiles/apple-iphone-15/reviews` → `["mobiles", "apple-iphone-15",
     "reviews"]`).
   - Each segment becomes (or reuses) a `TreeNode`, nested under the
     previous segment.
   - The final segment of each URL gets its `url` field set to that
     actual URL. Intermediate segments keep `url: null` unless they
     were *also* independently listed in the sitemap.

4. **Save.** Written to `filestorage/sitemap/<site>.json`.

### Politeness / anti-ban measures

- A single `requests.Session` is reused for all requests to a site
  (one connection pool, one User-Agent).
- Every request is followed by a randomized delay
  (`MIN_DELAY`–`MAX_DELAY` seconds).
- Failed requests retry with exponential backoff + jitter
  (`MAX_RETRIES` attempts) before giving up on that URL.
- Requests run fully sequentially — no concurrency, no parallel hosts.

---

## 4. Usage

```bash
python filestorage/treeConstructor.py
python filestorage/treeConstructor.py --input backend/site-list.txt --output filestorage/sitemap
```

| Flag | Default | Meaning |
|---|---|---|
| `--input` | `backend/site-list.txt` | Path to the site list file. |
| `--output` | `filestorage/sitemap` | Directory to write `<site>.json` files into. |

---

## 5. Downstream files that consume this format

- **`FilterMobileUrls.py`** reads `filestorage/sitemap/*.json`, walks
  the `tree`, and outputs only the branches whose `path` contains a
  mobile-related keyword — see `filestorage/sitemap_mobile/<site>.json`
  for that narrower format.
- **`ExtractMobile.py`** crawls actual listing pages (not sitemaps) to
  pull out individual phone products (title/price/url/image) — a
  different, flatter JSON shape, saved to `filestorage/mobiles/<site>.json`.
