# JSON → CSV → PostgreSQL pipeline

This is the landing-to-database stage for MobileInfoAnalytics. It consumes the
normalized JSON written by the site navigators; it does not scrape pages.

## Data contract and source lineage

All implemented scrapers write the shape in `filestorage/template.json`. The
navigators currently save only that template, so the original page URL is
recovered before any database load.

| JSON directory | Database schema | Filename → URL rule |
|---|---|---|
| `gsmarena.com` | `original` | `gsmarena__<page>.json` → `https://www.gsmarena.com/<page>` |
| `daraz.pk` | `daraz` | `daraz__<page>.json` → `/products/<page>` |
| `mymobile.pk` | `mymobile` | `mymobile__<slug>.json` → `/products/<slug>/` |
| `mega.pk` | `mega` | Must resolve through `sitemap_mobile/mega.pk.json`; the filename does not retain `/mobiles_products/<id>/` |
| `whatamobile.com.pk` | `whatamobile` | `whatamobile__<slug>.json` → `/product/<slug>/` |
| `whatmobile.com.pk` | `whatmobile` | `whatmobile__<page>.json` → `/<page>` |

Resolution priority is: an explicit future `source_url` field, a filtered
manifest/catalog-discovery record, then a deterministic filename rule. An
ambiguous or unrecoverable URL goes to `_manifest/errors.csv`; the converter
never fabricates one. This preserves the URL needed by the eventual database
even though current phone JSON has no URL field.

The JSON file modification time is used as `data_snapshot` in UTC. For an
import with a known crawl timestamp, supply `--snapshot-at` explicitly.

## 1. Create the CSV hierarchy

From the repository root in Windows PowerShell:

```powershell
python .\filestorage\jsonToCsv.py
```

Useful options:

```powershell
# One source only
python .\filestorage\jsonToCsv.py --site gsmarena.com

# One known timestamp for an imported crawl batch
python .\filestorage\jsonToCsv.py `
  --snapshot-at 2026-08-17T12:00:00+00:00

# Stop immediately on bad JSON or unresolved lineage
python .\filestorage\jsonToCsv.py --strict
```

Output is streamed into `filestorage/csvs/`:

```text
csvs/
├── _manifest/
│   ├── manifest.json
│   ├── records.csv
│   └── errors.csv
├── original/
│   ├── records.csv             # canonical loader input
│   ├── central_info.csv
│   ├── network.csv ... battery.csv
│   └── raw_ingest.csv
└── <marketplace>/
    ├── records.csv             # canonical loader input
    ├── secondary_info.csv
    ├── central_info.csv        # matching status, not guessed IDs
    ├── network.csv ... battery.csv
    └── raw_ingest.csv
```

`record_key` is a stable SHA-256 staging key derived from schema + source URL.
Database identity values are assigned by PostgreSQL and must not be inferred
from CSV row order.

The per-table files make the normalized hierarchy inspectable and usable with
Athena/Synapse. `csvToDataBase.py` intentionally loads `records.csv`, including
its lossless `payload_json`, through transactional SQL functions. This avoids
partial parent/detail inserts and unstable client-generated surrogate IDs.

## 2. Initialize PostgreSQL/Supabase

Run these files in order using the Supabase SQL editor or `psql`:

```text
db/schema_v1.sql
db/functions_v1.sql
```

The schema migration creates private data schemas. Only `api.*` security-
definer functions are granted to Supabase `service_role`; `anon` and
`authenticated` receive no direct ETL access.

## 3. Validate, then load

Install dependencies and validate without a database:

```powershell
python -m pip install -r .\requirements.txt
python .\filestorage\csvToDataBase.py --dry-run
```

Load Supabase using its **direct PostgreSQL or pooler connection string**, not
the browser REST URL or API key:

```powershell
$env:SUPABASE_DB_URL = "postgresql://...?...sslmode=require"
python .\filestorage\csvToDataBase.py --target supabase
```

The connection string is read from the environment and is never written to a
CSV or log. Ingestion is idempotent by source URL and snapshot. A failed batch
is rolled back and retried row-by-row; rejects are recorded both in
`warehouse.etl_rejects` and
`filestorage/csvs/_manifest/database_failures.csv`.

Common controls:

```powershell
# Test a small batch
python .\filestorage\csvToDataBase.py --limit 100

# Load selected sources
python .\filestorage\csvToDataBase.py `
  --schema original --schema mega --batch-size 500

# Stop instead of quarantining a bad row
python .\filestorage\csvToDataBase.py --stop-on-error
```

## Product matching

`original.central_info` is the master GSMArena product. Marketplace payloads
are always stored in `secondary_info`, even when no master match exists. The
strict `central_info.product_id NOT NULL` relation is created only after:

1. an unambiguous normalized-name match, or
2. an explicit reviewed mapping.

An explicit map is a CSV with:

```csv
source_schema,source_url,product_id
mega,https://www.mega.pk/mobiles_products/23647/Example.html,123
```

Load it with:

```powershell
python .\filestorage\csvToDataBase.py --master-map .\reviewed_matches.csv
```

Fuzzy matching is intentionally not automatic in v1: a false product merge is
harder to repair than an unmatched listing. Review unmatched rows with
`api.unmatched_listings()` and link one using
`api.link_source_product(schema, source_serial_number, product_id)`.

## Analytics functions

The following Supabase/PostgreSQL functions cover the requests in
`db/functions_layout.txt`:

- `api.complete_listings(minimum, matched_only, source_schema)`
- `api.unmatched_listings(source_schema)`
- `api.price_comparison(product_id)`
- `api.product_price_history(product_id, from, to)`
- `api.site_price_summary(from, to)`
- `api.product_bundle(product_id)`
- `api.refresh_exact_name_links(source_schema)`

Marketplace prices are tagged `PKR`. GSMArena's `Price[]` can contain multiple
currencies whose positions are not labeled by the scraper, so those historical
rows deliberately keep `currency_code = NULL` instead of being falsely marked
as PKR.

