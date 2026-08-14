# WhatMobile catalogue pipeline

WhatMobile serves product details in server-rendered `table.specs` elements.
The filter therefore builds a WhatMobile-specific catalogue manifest from
brand and price listing URLs, excluding the prior keyword-only noise such as
`StolenMobile.php`. The navigator keeps each listing page open, opens each
phone detail page in a second Playwright page, and writes a normalized JSON
file atomically.

## Build the manifest

```powershell
python .\filestorage\FilterMobileUrls.py --site whatmobile.com.pk --dry-run
python .\filestorage\FilterMobileUrls.py --site whatmobile.com.pk
```

## Crawl a range

```powershell
python .\backend\navigation_to_page\www.whatmobile.com.pk.py --min 1 --max 100
```

Ranges are one-based and inclusive. Existing valid output JSON is skipped but
retains its original position. Use `--dry-run` to review catalog seeds without
opening a browser, `--headed` to show Chromium, or `--force` to re-scrape.

Before a live run, respect `https://www.whatmobile.com.pk/robots.txt`; do not
use the disallowed search, preview, lookup, or mobile routes. Use conservative
delays (the defaults are 2–5 seconds) and stop if the site blocks access.

## Verification

```powershell
python -m unittest discover -s tests -v
python -m py_compile .\backend\scrapers\www.whatmobile.com.pk.py .\backend\navigation_to_page\www.whatmobile.com.pk.py .\filestorage\FilterMobileUrls.py
```
