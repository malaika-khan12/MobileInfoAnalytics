# GSMArena crawl safety and Windows usage

The GSMArena navigator is resumable, but it is intentionally not an unlimited
crawler. A third-party server decides whether automation is allowed, so no
delay or browser setting can guarantee that an IP address will never be rate
limited. Obtain permission and check GSMArena's current terms and robots rules
before collecting data at scale. A new network does not cancel a server's
request to stop; do not use network or proxy changes to bypass a refusal.

## Why the previous run was stopped

The log contained `HTTP 429` and `Retry-After: 36000`. That value means **make
no follow-up request for at least 36,000 seconds (10 hours)**. The old behavior
reduced that to a 300-second cooldown. The command also used 15--25 second page
spacing and `--load-assets`, which could create many scripts, stylesheets,
images, advertisements, and other requests for every phone page.

The corrected navigator now:

- honors the complete `Retry-After` value and adds a five-minute guard;
- persists cooldowns and rolling request history across process restarts;
- stops immediately on HTTP 403, 429, 503, redirects to refusal pages, and
  recognizable block pages;
- never retries a refusal and defaults to zero retries;
- allows only one same-site top-level HTML document per navigation and blocks
  all scripts, styles, images, fonts, media, XHR/fetch, frames, and third-party
  requests;
- reuses one stable browser context instead of rotating browser identities;
- disables proxy rotation and `--load-assets`;
- prevents two crawler processes from running concurrently;
- defaults to direct URLs from the filtered manifest, avoiding extra maker and
  pagination requests;
- enforces 90--150 seconds between documents, at most 30 documents per rolling
  hour, 150 per rolling 24 hours, and 25 per process.

These limits are conservative safeguards, not published GSMArena allowances.
They can be lowered, but the CLI will not let a run raise them.

## Before the next live request

Wait until at least 10 hours after the last 429 shown in the log. Because that
event happened before the new persistent state file existed, the revised code
cannot infer its original timestamp. Do not start early merely because the
internet connection changed.

Validate the exact range without making a network request:

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py `
  --sitemap .\filestorage\sitemap_mobile\gsmarena.com.json `
  --crawl-mode direct `
  --min 69 `
  --max 500 `
  --dry-run
```

After the earlier cooldown has genuinely expired, run the same range without
`--dry-run`:

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py `
  --sitemap .\filestorage\sitemap_mobile\gsmarena.com.json `
  --crawl-mode direct `
  --min 69 `
  --max 500
```

Do not add `--load-assets`, proxy arguments, or the former 15--25 second delay.
Headed mode is not needed for mass collection. Direct mode still invokes the
existing GSMArena scraper after each page is loaded and writes the same one-JSON
file-per-phone output.

## Expected safe stops and resume behavior

One process stops after 25 document requests with exit code `75`. This is
intentional. Run the **same command** later: valid phone JSON files are skipped,
and collection resumes at the next missing file. The rolling hourly and daily
budgets survive restarts, so immediately relaunching the command cannot reset
them.

The output directory contains these control files:

- `_request_policy.json`: recent request timestamps, limits, and any UTC
  cooldown deadline;
- `_crawl_summary.json`: saved/skipped/failed counts and the safe-stop reason;
- `_crawl.lock`: exists only while a crawler owns the source;
- `_failures.jsonl`: final non-policy scrape failures.

Inspect the policy in PowerShell:

```powershell
Get-Content .\filestorage\mobiles\gsmarena.com\_request_policy.json -Raw |
  ConvertFrom-Json |
  Format-List
```

If a 429 contains `Retry-After: 36000`, the run stops immediately and records a
UTC resume time about 10 hours and 5 minutes later. Any run before that time
exits without opening Playwright or making a request. Do not delete or edit the
policy file to get around the cooldown.

If the Python process crashes, `_crawl.lock` can remain. First confirm in Task
Manager that no crawler is running, then clear that one stale lock explicitly:

```powershell
python .\backend\navigation_to_page\www.gsmarena.com.py `
  --sitemap .\filestorage\sitemap_mobile\gsmarena.com.json `
  --min 69 `
  --max 500 `
  --clear-stale-lock
```

## Scale expectation

At the configured ceiling of 150 documents per 24 hours, 15,052 phone pages
would require roughly 101 days, excluding already completed files and any
server cooldowns. If that is not acceptable, the correct solution is a licensed
dataset, an approved API/data feed, or explicit higher-volume permission from
the source—not shorter delays, concurrency, proxies, or identity rotation.
