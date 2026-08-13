# Copy-paste prompt for implementing the remaining MobileInfoAnalytics crawlers

Replace `[TARGET_SITE]` with one site from the allowed list below, then give
everything between `BEGIN PROMPT` and `END PROMPT` to the coding LLM. Reuse the
prompt for each site, one site at a time.

---

## BEGIN PROMPT

You are a senior Python scraping engineer working inside an existing repository
named `MobileInfoAnalytics`. Your task is to inspect the repository and
implement a production-quality, Windows-compatible scraper and mass crawler for
this target:

```text
TARGET_SITE = [TARGET_SITE]
```

Do not give me only general advice, pseudocode, or isolated snippets. Inspect
the real files first, then implement the complete target-site files, tests, and
usage documentation. If you can edit the repository, make the edits and run the
tests. If you cannot access a file needed to make site-specific selectors,
request that exact file or HTML sample instead of inventing selectors.

## 1. Project purpose

`MobileInfoAnalytics` collects normalized mobile-phone specifications and
prices from several authorized sources. Each site has two distinct modules:

1. A **scraper module** parses one already-loaded product page and converts it
   to the repository's common phone JSON schema.
2. A **navigation module** is the executable mass crawler. It discovers or
   reads product URLs, drives Playwright, invokes the scraper for each product,
   and saves one JSON file per phone.

The overall data flow is:

```text
backend/site-list.txt
        -> filestorage/treeConstructor.py
        -> filestorage/sitemap/<site>.json
        -> filestorage/FilterMobileUrls.py
        -> filestorage/sitemap_mobile/<site>.json
        -> backend/navigation_to_page/<site>.py --min N --max M
        -> listing/catalog page(s), pagination, and phone detail pages
        -> backend/scrapers/<site>.py
        -> filestorage/mobiles/<site>/<site>__<URL-ending>.json
```

`treeConstructor.py` is considered good enough and must remain unchanged.

## 2. Repository layout and current context

The relevant repository structure is:

```text
MobileInfoAnalytics/
├── backend/
│   ├── site-list.txt
│   ├── scrapers/
│   │   ├── README.md
│   │   ├── mymobile.pk.py
│   │   ├── priceoye.pk.py
│   │   ├── www.daraz.pk.py
│   │   ├── www.gsmarena.com.py
│   │   ├── www.mega.pk.py
│   │   ├── www.olx.com.pk.py
│   │   ├── www.whatamobile.com.pk.py
│   │   └── www.whatmobile.com.pk.py
│   └── navigation_to_page/
│       ├── README.md
│       ├── mymobile.pk.py
│       ├── priceoye.pk.py
│       ├── www.daraz.pk.py
│       ├── www.gsmarena.com.py
│       ├── www.mega.pk.py
│       ├── www.olx.com.pk.py
│       ├── www.whatamobile.com.pk.py
│       └── www.whatmobile.com.pk.py
├── filestorage/
│   ├── treeConstructor.py
│   ├── FilterMobileUrls.py
│   ├── template.json
│   ├── sitemap/
│   │   └── <site>.json
│   ├── sitemap_mobile/
│   │   └── <site>.json
│   └── mobiles/
│       └── <site>/
├── tests/
├── requirements.txt
└── README.md
```

Some target-site Python files may be empty placeholders, incomplete, or old.
Do not assume they already work merely because they exist.

The completed GSMArena modules are the primary architectural reference:

```text
backend/scrapers/www.gsmarena.com.py
backend/navigation_to_page/www.gsmarena.com.py
filestorage/FilterMobileUrls.py
tests/test_gsmarena_pipeline.py
README_GSMARENA_PIPELINE.md
```

Read those files completely before implementing the target. Reuse their
cross-platform patterns where appropriate, but do not copy GSMArena selectors
or URL regular expressions into another site.

Trust executable code and current manifests over stale prose when they
conflict. Preserve unrelated user changes in the repository.

## 3. Authorized scope

The repository's current `backend/site-list.txt` contains:

```text
MAIN_SITE:
https://www.gsmarena.com

SITES:
https://priceoye.pk/mobiles/
https://www.whatmobile.com.pk/
https://www.daraz.pk/
https://www.mega.pk/mobiles_products/
https://mymobile.pk/
https://www.whatamobile.com.pk/

UNAUTHORIZED_SITES:
https://qeemat.com.pk/
https://asaanprice.com/
https://qmart.pk/
https://wisemarket.com.pk/collection/mobiles/
https://www.urdupoint.com/mobile/
https://phonebolee.com/
https://whatmobilepriceoye.com/
```

For this assignment:

- GSMArena is already the working reference implementation.
- **Do not create, modify, test, or crawl PriceOye. It is owned by another team
  member.**
- Implement only one of these remaining authorized targets per iteration:
  - `whatmobile.com.pk`
  - `daraz.pk`
  - `mega.pk`
  - `mymobile.pk`
  - `whatamobile.com.pk`
- Do not work on OLX merely because placeholder files exist. It is not in the
  current authorized site list.
- Never request or crawl anything under `UNAUTHORIZED_SITES:`.
- Before live crawling, inspect the target's current `robots.txt`, terms, and
  access behavior. Follow applicable restrictions and use a conservative rate.
- Do not bypass authentication, CAPTCHAs, access controls, or explicit blocks.
  Do not implement stealth plugins or adversarial anti-bot circumvention.

If `TARGET_SITE` is PriceOye, GSMArena, OLX, or an unauthorized host, stop and
explain that it is outside this assignment.

## 4. Files to inspect before coding

Start by reading, not guessing. At minimum inspect:

```text
backend/site-list.txt
backend/scrapers/README.md
backend/navigation_to_page/README.md
filestorage/template.json
filestorage/FilterMobileUrls.py
filestorage/sitemap/<target-site>.json
filestorage/sitemap_mobile/<target-site>.json
backend/scrapers/www.gsmarena.com.py
backend/navigation_to_page/www.gsmarena.com.py
tests/test_gsmarena_pipeline.py
backend/scrapers/<target-site>.py
backend/navigation_to_page/<target-site>.py
requirements.txt
```

Report briefly what you found before changing code:

- the target filenames and expected class name;
- whether the filtered manifest contains direct product URLs, catalog/listing
  URLs, a tree, or a mixture;
- reliable target-site product URL rules;
- reliable category/listing seed URLs;
- pagination type: numbered links, next link, load-more button, or infinite
  scroll;
- whether phone specifications are in HTML tables, accordions, JSON-LD,
  embedded application state, or another stable structure;
- whether the price and variants are rendered server-side or require browser
  execution;
- any conflict between current files and this prompt.

If the filtered manifest is stale or selects category/search pages instead of
product pages, fix only the target-specific filtering behavior needed in
`FilterMobileUrls.py`. Do not rewrite `treeConstructor.py`.

## 5. Required deliverables for one target site

Implement or replace:

```text
backend/scrapers/<target-site>.py
backend/navigation_to_page/<target-site>.py
```

Also add or update:

```text
tests/test_<target_identifier>_pipeline.py
README_<TARGET_IDENTIFIER>_PIPELINE.md
```

Modify `filestorage/FilterMobileUrls.py` only when the target manifest cannot
reliably distinguish product pages and catalog seeds. Modify
`requirements.txt` only when a dependency is truly necessary; prefer the
existing standard library, BeautifulSoup, and Playwright stack.

Do not modify:

```text
filestorage/treeConstructor.py
filestorage/template.json keys or nesting
PriceOye files
GSMArena files, except for a clearly shared and tested bug fix
frontend/ or db/ files
unauthorized-site files
```

## 6. Mandatory public command

Normal crawling must require only the target's single navigation file and the
inclusive phone range:

```powershell
python .\backend\navigation_to_page\<target-site>.py --min 1 --max 100
```

The script itself must know its default manifest and output directory. The
operator must not need to pass `--sitemap`, `--output-dir`, catalog URL, maker,
or scraper path for an ordinary run.

Required range semantics:

- `--min` is the first phone position, **1-based and inclusive**.
- `--max` is the last phone position, **1-based and inclusive**.
- `--min 1 --max 100` processes at most positions 1 through 100.
- `--min 101 --max 200` processes positions 101 through 200.
- Default `--min` is `1`.
- Omitting `--max` means continue to the end.
- Reject `--min 0`, negative values, and `--max < --min` with a clear argparse
  error before opening a browser.
- If `--max` exceeds the number of eligible phones, process through the actual
  end and report the count honestly.
- Existing valid output files inside the range are `SKIP`, not failures.
- A skipped existing file still owns its original position. Do not scrape an
  extra later URL to compensate.
- Deduplicate product URLs before assigning positions.
- Preserve a deterministic discovery order. Direct mode uses manifest order.
  Catalog mode uses catalog-seed order, page order, and phone-card DOM order.
- Record the effective `range_min` and `range_max` in the crawl summary.

Support these optional diagnostic/advanced flags where applicable:

```text
--dry-run
--headed
--force
--retries N
--delay-min SECONDS
--delay-max SECONDS
--navigation-timeout-ms N
--selector-timeout-ms N
--load-assets
--sitemap PATH
--output-dir PATH
--log-level DEBUG|INFO|WARNING|ERROR
```

A positional single product URL may remain available for smoke testing. The
normal mass-crawl path must still be the simple `--min/--max` command.

For compatibility with older commands, `--limit N` may be retained as a
deprecated alias meaning “process N phone positions beginning at `--min`.” It
must not be allowed together with `--max`.

Examples expected after implementation:

```powershell
python .\backend\navigation_to_page\www.whatmobile.com.pk.py --min 1 --max 100
python .\backend\navigation_to_page\www.daraz.pk.py --min 1 --max 100
python .\backend\navigation_to_page\www.mega.pk.py --min 1 --max 100
python .\backend\navigation_to_page\mymobile.pk.py --min 1 --max 100
python .\backend\navigation_to_page\www.whatamobile.com.pk.py --min 1 --max 100
```

Only the command matching `TARGET_SITE` needs to work in the current
iteration.

## 7. Required catalog-to-product workflow

The desired visible workflow is like a phone-brand or mobile-category page:

1. Load a catalog/listing landing page from the filtered sitemap tree.
2. Wait for actual phone cards to be present.
3. Extract phone-detail links in DOM order.
4. Deduplicate and validate each link as a real product page on the authorized
   host.
5. Follow all in-scope pagination/load-more/infinite-scroll pages in a
   deterministic order.
6. For each selected phone position, open its detail page in a second
   Playwright page in the same browser context.
7. Wait for the page structure required by the target scraper.
8. Get the fully rendered HTML with `page.content()`.
9. Pass that HTML and source URL to the target scraper class.
10. Validate the normalized result.
11. Save one strict JSON file atomically.
12. Close the detail page, return focus to the listing page, and continue to
    the next phone.
13. Stop as soon as the inclusive `--max` position has been handled.

Keeping the listing page open and using a temporary detail page is preferred
to repeatedly using `go_back()`: it preserves listing pagination/scroll state
and matches the project's intended browser workflow.

Some sites may already have trustworthy direct product URLs in
`sitemap_mobile/<site>.json`. Implement the modes the actual site supports:

- **catalog mode:** browse listing seeds and discover product pages live;
- **direct mode:** visit validated product URLs directly from the manifest;
- **auto/hybrid mode:** prefer catalog traversal when reliable catalog seeds
  exist, while retaining direct URLs as a coverage/retry fallback.

Do not force a GSMArena-style maker tree onto a site with a different
information architecture. The external interface and saved schema stay
uniform; the internal discovery logic must be site-specific.

## 8. Scraper-module contract

The scraper module handles one already-loaded product page. It must not own the
mass crawl, browser lifecycle, retries, delays, proxies, or output loop.

Use one importable target-specific class, following the repository's existing
naming style. Its conceptual API should match:

```python
class TargetSiteScraper:
    def __init__(self, html: str, source_url: str | None = None) -> None:
        ...

    def scrape(self) -> dict:
        """Extract a loss-minimizing raw representation from one page."""
        ...

    def to_template(self, raw: dict) -> dict:
        """Map raw fields to the exact common template."""
        ...
```

The separation matters:

- `scrape()` should preserve useful source labels/sections that the common
  schema cannot currently represent.
- `to_template()` performs normalization, Yes/No conversion, list conversion,
  fingerprint classification, numeric price parsing, and common-key mapping.
- Do not fabricate specifications that are absent from the page.
- Keep site-specific selectors and source-label mappings in this module.
- Favor semantic labels, JSON-LD, and stable data attributes over fragile
  absolute CSS paths or `nth-child` selectors.
- Normalize whitespace and Unicode without destroying meaningful units.
- Handle repeated rows and optional sections.
- Treat a page with no reliable phone name/product identity as a scrape
  failure, not a successful empty record.

Because filenames contain dots, normal package imports may not work. Follow the
existing GSMArena navigator's safe `importlib.util.spec_from_file_location`
pattern if needed.

An optional scraper-only debug CLI may accept a saved HTML file and print raw
or normalized output, but importing the class must have no side effects.

## 9. Exact normalized JSON schema

`filestorage/template.json` contains comments and trailing commas, so it is a
human template rather than strict JSON. Do not load it directly with
`json.loads()` unless comments/trailing commas are removed safely. Every saved
phone result, however, must be valid strict JSON with this exact key spelling
and nesting:

```json
{
  "MobileName": "Xiaomi Redmi Note 14 4G",
  "Network": {
    "2G": 1,
    "3G": 1,
    "4G": 1,
    "5G": 0
  },
  "Launch": {
    "Announced": "2025, January 10",
    "Status": "Available. Released 2025, January 15"
  },
  "Body": {
    "Dimensions": "163.3 x 76.6 x 8.2 mm (6.43 x 3.02 x 0.32 in)",
    "Weight": "196.5 g (6.95 oz)",
    "Build": "Glass front, plastic back, aluminum frame",
    "SIM": "Nano-SIM + Nano-SIM",
    "Protection": "IP54 dust protected and water resistant"
  },
  "Display": {
    "Type": "AMOLED, 120Hz",
    "Size": "6.67 inches",
    "Resolution": "1080 x 2400 pixels",
    "Protection": "Corning Gorilla Glass 5"
  },
  "Platform": {
    "OS": "Android 14",
    "Chipset": "Mediatek Helio G99 Ultra (6 nm)",
    "CPU": "Octa-core",
    "GPU": "Mali-G57 MC2"
  },
  "Memory": {
    "Card slot": "microSDXC (uses shared SIM slot)",
    "Types": [
      "128GB 6GB RAM",
      "256GB 8GB RAM"
    ],
    "Technology": "UFS 2.2"
  },
  "Main Camera": {
    "Specifications": [
      "108 MP, f/1.7, wide",
      "2 MP, macro"
    ],
    "Features": "LED flash, HDR, panorama",
    "Video": [
      "1080p@30fps",
      "1080p@60fps"
    ]
  },
  "Selfie Camera": {
    "Specifications": [
      "20 MP, f/2.2, wide"
    ],
    "Video": [
      "1080p@30fps"
    ]
  },
  "Sound": {
    "Loudspeaker": "Yes, with stereo speakers",
    "3.5mm jack": 1
  },
  "Features": {
    "WLAN": "Wi-Fi 802.11 a/b/g/n/ac, dual-band",
    "Bluetooth": "5.3",
    "Positioning": "GPS, GLONASS, BDS, GALILEO",
    "NFC": 1,
    "Infrared port": 1,
    "Radio": 0,
    "USB": "USB Type-C 2.0, OTG",
    "BackFingerPrint": 0,
    "SideFingerPrint": 0,
    "InDisplayFingerPrint": 1,
    "Sensors": "Fingerprint (under display), accelerometer, gyro, compass"
  },
  "Battery": {
    "Capacity": "5500 mAh",
    "WirelessCharging": 0,
    "Charging": [
      "33W wired"
    ]
  },
  "Colors": [
    "Midnight Black",
    "Mist Purple",
    "Ocean Blue",
    "Lime Green"
  ],
  "Weight": "1.00 W/kg (head), 0.97 W/kg (body)",
  "Price": [
    172.99,
    206.8,
    129.99,
    48000
  ]
}
```

Important schema semantics:

- `Body.Weight` is the physical phone weight.
- The confusing top-level `Weight` key represents SAR/exposure information in
  the current template. Do not put physical grams there.
- Boolean-like capability fields use `1` for verified yes and `0` for verified
  no. Use `null` when the page does not establish either state; do not turn
  “not mentioned” into false.
- Missing scalar fields should be `null`, not invented marketing text.
- Missing list fields should be `[]`.
- Preserve every required key even when its value is unavailable.
- Arrays must remain arrays even when there is only one element.
- `Price` contains numeric values only. Strip currency symbols and grouping
  separators carefully, but do not include installment amounts, discount
  percentages, review counts, or unrelated numbers. Do not convert currencies
  unless the repository later defines a conversion policy. Document the
  target site's source-currency assumption in the target README.
- If a commerce site exposes only a subset of specifications, populate that
  verified subset and leave other fields null/empty. Never enrich from a
  different website during this task.

The example values above are illustrative. The keys and types are the
contract; the values must come from the current target product page.

## 10. Product URL and catalog filtering

Keyword matching such as “mobile” is not enough. Build and test target-specific
rules based on the actual sitemap and page structure.

A product URL validator should normally verify all of the following:

- exact authorized canonical host, allowing only intentional `www` variants;
- acceptable scheme and normalized URL;
- a target-specific product path or identifier pattern;
- absence of category, search, compare, review-only, image-only, login, cart,
  seller, help, and pagination-only patterns;
- no unexpected cross-domain redirect;
- no fragment-only duplicates;
- a canonicalized query policy that keeps only product-defining parameters.

A catalog validator should separately recognize category/brand/listing seeds.
Do not use one permissive regex for both products and listings.

The filtered manifest should retain useful source metadata and counts. If the
site supports both catalog and direct URLs, a combined shape analogous to this
is acceptable:

```json
{
  "site": "example.com",
  "base_url": "https://example.com",
  "mode": "catalog_tree",
  "strategy": "example_catalog_and_product_pages",
  "source_url_count": 12345,
  "catalog_count": 42,
  "match_count": 900,
  "tree": {
    "name": "catalogs",
    "path": "/",
    "url": "https://example.com/mobiles",
    "children": []
  },
  "catalog_urls": [
    {"url": "https://example.com/mobiles/brand-a"}
  ],
  "mobile_urls": [
    {"url": "https://example.com/product/phone-a"}
  ]
}
```

Adapt the shape to the current `FilterMobileUrls.py` conventions rather than
creating an incompatible parallel format.

## 11. Navigation and mass-crawl reliability requirements

The navigation module owns all browser and crawl concerns:

- use Playwright's synchronous Python API unless the repository has already
  standardized on async;
- default to headless Chromium; `--headed` is for visual debugging;
- use a browser context per catalog/session, not a brand-new browser process
  per phone;
- block images, media, and fonts by default for speed; `--load-assets` disables
  that optimization for visual tests;
- wait for a meaningful product/listing selector, not only `networkidle`;
- validate HTTP status when a response is available;
- validate the final host after redirects;
- close every temporary detail page in `finally`;
- close contexts, browser, and Playwright in `finally`/context-manager cleanup;
- apply conservative randomized delays between requests;
- retry transient navigation/time-out failures with bounded exponential
  backoff;
- never retry permanent validation errors forever;
- preserve completed files on `Ctrl+C` and return exit code `130`;
- use clear timestamped logging with catalog, phone position, URL, attempt, and
  final summary;
- do not silently swallow exceptions.

Proxy support, if retained from the reference implementation, must accept only
operator-supplied proxy values/files. Do not scrape public proxies or claim
that proxy rotation makes a prohibited crawl acceptable.

## 12. Persistence, filenames, resume, and failure records

Default output directory:

```text
filestorage/mobiles/<target-site>/
```

One product produces one normalized JSON file. Follow the repository naming
convention:

```text
sitename__endofURL.json
```

Example:

```text
gsmarena__xiaomi_redmi_note_14_4g_(global)-13616.php.json
```

Sanitize Windows-invalid filename characters (`<>:"/\\|?*` and control
characters), remove trailing dots/spaces, and keep names deterministic. Detect
collisions for sites whose products are distinguished only by query strings;
if necessary, add a short deterministic URL hash while preserving the prefix
convention.

Write JSON atomically:

1. create the parent directory;
2. write UTF-8 strict JSON to a temporary file in the same directory;
3. flush/close it;
4. replace the destination with `os.replace()`.

An existing file is resumable only if it parses as JSON, is an object, contains
a non-empty `MobileName`, and conforms to the required top-level structure.
Skip valid files unless `--force` is given. Re-scrape corrupt or incomplete
files.

Write these control files beside the phone JSONs where relevant:

```text
_crawl_summary.json
_failures.jsonl
_catalog_discovery.json
_catalog_coverage.json
```

Minimum summary fields:

```text
site, manifest, output_dir, crawl_mode,
started_at, finished_at,
range_min, range_max,
manifest_records_seen, manifest_duplicates, manifest_rejected,
eligible_product_urls, products_discovered, duplicate_products_discovered,
selected_urls, already_complete, succeeded, failed, interrupted
```

Each final failure JSONL record should include timestamp, kind, URL, source
catalog page if applicable, output filename, attempt count, exception type, and
message. Never include credentials or proxy passwords in logs.

## 13. Windows setup and execution

The teammate runs native Windows PowerShell from:

```text
D:\Downloads\Repositories\MobileInfoAnalytics
```

Use `pathlib.Path`; do not hard-code that absolute path. Resolve repository
defaults relative to the navigation script, so invocation works from the
repository root and remains cross-platform.

Expected environment setup:

```powershell
cd D:\Downloads\Repositories\MobileInfoAnalytics
python -m pip install -r .\requirements.txt
python -m playwright install chromium
```

Expected target verification sequence:

```powershell
python .\backend\navigation_to_page\<target-site>.py --help
python .\backend\navigation_to_page\<target-site>.py --dry-run --min 1 --max 5
python .\backend\navigation_to_page\<target-site>.py --min 1 --max 3 --headed --load-assets
python .\backend\navigation_to_page\<target-site>.py --min 1 --max 25
python .\backend\navigation_to_page\<target-site>.py --min 1 --max 25
```

The second `1..25` run must show valid files as `SKIP` and must not duplicate
records.

Use PowerShell backticks only when presenting a multiline PowerShell command;
provide a one-line version too. Do not use Bash backslashes in Windows
instructions.

## 14. Required tests

Add offline tests that do not require a live network for normal CI. At minimum
cover:

1. accepted product URLs;
2. rejected categories/search/reviews/foreign hosts;
3. accepted catalog seed and pagination URLs;
4. manifest loading for the actual target shape;
5. duplicate removal while preserving first-seen order;
6. `--min/--max` validation;
7. exact 1-based inclusive slicing (`2..3` selects only positions 2 and 3);
8. catalog traversal where an earlier phone is discovered but not scraped
   because it is below `--min`;
9. stopping immediately after `--max`;
10. pagination or load-more discovery;
11. scraper mapping from representative saved HTML fixtures;
12. missing optional sections;
13. exact template keys/nesting and strict JSON serialization;
14. Windows-safe deterministic filenames;
15. atomic save behavior;
16. corrupt-output re-scrape and valid-output resume skip;
17. failure JSONL and summary counts;
18. browser/page/context cleanup using fakes or mocks.

Use at least three representative product fixtures when available:

- one current/full product page;
- one older or sparse product page;
- one variant/layout edge case.

Do not claim selectors are live-tested unless you actually ran a live smoke
test. If live access is unavailable, say so and identify the exact verification
command the teammate must run.

Run the repository suite after target tests:

```powershell
python -m unittest discover -s tests -v
```

Do not fix unrelated failing tests without explaining and obtaining agreement.

## 15. Implementation quality rules

- Use type hints and concise docstrings on public classes/functions.
- Keep scraping, normalization, navigation, persistence, and CLI concerns
  separated.
- Use `logging`, not scattered `print()`, except for intentional JSON output in
  single-URL or dry-run modes.
- Use `pathlib`, `urllib.parse`, `json`, `re`, and standard-library tools where
  sufficient.
- Do not use `eval()` on page data.
- Do not parse prices or measurements with a single overly broad “all numbers”
  regex.
- Do not overwrite a good output with an empty or invalid parse.
- Do not save HTML or screenshots for every phone unless a debug flag requests
  them.
- Do not load unnecessary assets during mass crawling.
- Do not create a generic universal scraper with guessed mappings. Each target
  needs verified site-specific extraction logic behind a common interface.
- Avoid unnecessary repository-wide refactors. Deliver one verified target at
  a time.

## 16. How to proceed in this session

Follow this order:

1. Confirm that `TARGET_SITE` is one of the five allowed remaining sites.
2. Inspect all files listed in section 4.
3. Summarize the actual manifest shape, product/catalog URL patterns, page
   structure, and current placeholder status.
4. State a short implementation plan.
5. Implement the scraper module.
6. Implement or correct target-specific filtering only if needed.
7. Implement the navigation module with the mandatory `--min/--max` contract.
8. Add offline tests and fixtures.
9. Run compilation and tests.
10. Present the exact Windows smoke-test and mass-crawl commands.
11. Report changed files, test results, any selectors requiring live
    confirmation, and any known coverage gaps.

If you cannot inspect the repository directly, ask me to attach only these
items before writing final code:

- the two current target Python files;
- the target full and filtered sitemap JSON files or representative excerpts;
- one listing-page rendered HTML sample;
- two or three product-page rendered HTML samples;
- the current GSMArena reference navigator and scraper;
- `filestorage/template.json`.

Do not fabricate target-site HTML, URL shapes, or CSS selectors to avoid this
inspection step.

## 17. Completion criteria

The target is complete only when all of the following are true:

- the single navigation file runs on native Windows;
- `--help` visibly contains `--min` and `--max`;
- an ordinary crawl needs no path arguments;
- ranges are 1-based and inclusive;
- discovery reaches genuine target-site phone pages and follows pagination;
- every selected product is passed to the one-page scraper;
- outputs use the exact common schema and strict JSON;
- filenames are deterministic and legal on Windows;
- valid outputs resume as skips;
- failures are logged and do not erase successful work;
- cleanup and `Ctrl+C` behavior are safe;
- offline tests pass;
- PriceOye, GSMArena, `treeConstructor.py`, unauthorized sites, frontend, and
  database code remain untouched unless explicitly authorized.

Begin by inspecting the repository and reporting the target-specific facts.
Then implement the code rather than stopping after the plan.

## END PROMPT

