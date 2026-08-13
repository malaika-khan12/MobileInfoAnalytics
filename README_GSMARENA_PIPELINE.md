# GSMArena catalogue-tree and mass-scraping pipeline

This bundle implements the browser workflow represented by a GSMArena maker
page such as `https://www.gsmarena.com/xiaomi-phones-80.php` without changing
`filestorage/treeConstructor.py` or the existing single-page scraper.

```text
full 200,000-URL sitemap tree
        -> maker landing-page tree + direct product fallback
filtered GSMArena manifest
        -> maker page -> phone card -> specification page -> scraper
one JSON file per phone
```

The browser keeps the maker/listing page open. For each phone card it opens a
second page, invokes `GsmarenaScraper`, saves the JSON atomically, closes the
detail page, and returns focus to the listing. It then follows the maker page's
pagination and repeats.

## 1. Files to replace

Replace these files with the bundle versions:

```text
filestorage/FilterMobileUrls.py
backend/navigation_to_page/www.gsmarena.com.py
```

Keep the existing files below unchanged:

```text
filestorage/treeConstructor.py
backend/scrapers/www.gsmarena.com.py
```

The included `requirements.txt` pins the Playwright version already proven by
your successful Windows-headed and WSL-headless logs.

Your `unrecognized arguments: --crawl-mode --maker` output is not a
PowerShell or Playwright failure. It proves that Windows is still running the
older direct-only navigator. Likewise,
`strategy=gsmarena_product_pages` proves that the older filter is still in
place. Replace **both** files above before testing again. After replacement,
this command must list `--crawl-mode`, `--maker`, `--min`, and `--max`:

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py --help
```

## 2. Build the combined GSMArena manifest

Preview first:

```powershell
python .\filestorage\FilterMobileUrls.py --site gsmarena.com --dry-run
```

The log now shows two samples:

- canonical catalogue landings such as `nokia-phones-1.php` and
  `xiaomi-phones-80.php`;
- direct product fallback URLs such as `nokia_3210_(1999)-6.php`.

Write the manifest after checking those samples:

```powershell
python .\filestorage\FilterMobileUrls.py --site gsmarena.com
```

Only `filestorage/sitemap_mobile/gsmarena.com.json` is replaced. The source
tree remains untouched.

The generated manifest contains:

```json
{
  "mode": "catalog_tree",
  "strategy": "gsmarena_catalog_and_product_pages",
  "catalog_count": 0,
  "match_count": 15052,
  "tree": {
    "url": "https://www.gsmarena.com/makers.php3",
    "children": [
      {
        "url": "https://www.gsmarena.com/xiaomi-phones-80.php",
        "maker_slug": "xiaomi",
        "maker_id": 80
      }
    ]
  },
  "catalog_urls": [],
  "mobile_urls": []
}
```

`catalog_count` will be the actual number found in your source tree; zero above
is only a schema placeholder. Your already verified product fallback count is
15,052.

## 3. Inspect the manifest and chosen crawl mode

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py --dry-run
```

With the new manifest, `resolved_crawl_mode` should be `catalog` and
`eligible_catalogs` should be greater than zero. The output also reports the
15,052 direct URLs retained as fallback.

## 4. Test exactly the Xiaomi page workflow

This is the most direct test of the requested interaction:

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py `
  "https://www.gsmarena.com/xiaomi-phones-80.php" `
  --min 1 `
  --max 5 `
  --headed `
  --load-assets
```

In headed mode you will see the Xiaomi listing remain available while phone
detail pages are opened, scraped, closed, and followed by the next card.
`--load-assets` is only for this visual test; omit it for efficient mass
scraping.

## 5. Test through the generated tree

Use only Xiaomi from the manifest:

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py `
  --sitemap .\filestorage\sitemap_mobile\gsmarena.com.json `
  --crawl-mode catalog `
  --maker xiaomi `
  --min 1 `
  --max 5 `
  --headed
```

Or select the same maker by its GSMArena id:

```text
--maker 80
```

## 6. Run an ordinary mass-scraping batch

The manifest and output paths are automatic. The only required batch controls
are the inclusive phone positions:

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py --min 1 --max 100
```

The next teammate or terminal can own a non-overlapping batch:

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py --min 101 --max 200
```

Ranges are 1-based and inclusive. Existing valid JSON files in the requested
range are skipped and still count as their stable positions; the crawler does
not replace them with later phones. This makes batch assignments deterministic
and safe to resume.

## 7. Run all maker catalogues

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py --min 1
```

`--crawl-mode auto` is the default and also chooses catalogue mode whenever
the manifest contains maker pages.

## 8. Direct fallback mode

The original direct-URL crawler remains available:

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py `
  --sitemap .\filestorage\sitemap_mobile\gsmarena.com.json `
  --crawl-mode direct `
  --min 1 `
  --max 5
```

This is useful for retrying coverage gaps without revisiting maker pages.

## Outputs and resume behavior

Phone records are stored in:

```text
filestorage/mobiles/gsmarena.com/
```

Additional control files are written alongside them:

| File | Purpose |
|---|---|
| `_crawl_summary.json` | Counts for the latest run. |
| `_catalog_discovery.json` | Maker pages, pagination pages, and phone URLs discovered during browsing. |
| `_catalog_coverage.json` | Comparison between catalogue discovery and the 15,052 direct sitemap URLs. |
| `_failures.jsonl` | Final catalog/product errors after retries. |

Every phone JSON is written atomically. On a rerun, valid existing phone files
are logged as `SKIP`; corrupt/incomplete files are scraped again. `Ctrl+C`
preserves completed outputs.

## Useful options

| Option | Meaning |
|---|---|
| `--crawl-mode auto` | Prefer catalogue traversal; fall back to direct URLs. |
| `--crawl-mode catalog` | Force maker-page traversal. |
| `--crawl-mode direct` | Use direct product URLs only. |
| `--maker xiaomi` | Select one maker by slug/name; repeatable. |
| `--maker 80` | Select one maker by GSMArena id. |
| `--catalog-limit N` | Traverse only the first `N` selected maker pages. |
| `--min N` | First phone position, 1-based and inclusive; default `1`. |
| `--max N` | Last phone position, 1-based and inclusive; omit for the end. |
| `--limit N` | Deprecated compatibility alias for `N` phones starting at `--min`. |
| `--headed` | Display Chromium. |
| `--load-assets` | Load images/fonts/media for visual debugging. |
| `--force` | Re-scrape valid existing phone outputs. |
| `--retries N` | Retry each failed page `N` times after its first attempt. |
| `--delay-min S` | Minimum post-request delay in seconds. |
| `--delay-max S` | Maximum post-request delay in seconds. |
| `--output-dir PATH` | Override the output directory. |
| `--proxy URL` | Use a user-provided proxy; repeat for rotation. |
| `--proxy-file PATH` | Read one user-provided proxy per line. |
| `--dry-run` | Validate inputs without opening Chromium. |

## Offline tests

```powershell
python -m unittest discover -s tests -v
```

The 16 tests cover product and maker classification, filtered-tree generation,
manifest compatibility, pagination discovery, product deduplication, inclusive
range selection, split catalog batches, the catalogue-to-product loop, atomic
saves, coverage reporting, and resume skips.

## Existing WSL warnings

The mirrored-networking and systemd-user-session warnings did not prevent the
crawler from working. Your logs confirm that WSL headless mode and Windows
headed mode both scrape successfully, so those warnings are independent of
this pipeline.
