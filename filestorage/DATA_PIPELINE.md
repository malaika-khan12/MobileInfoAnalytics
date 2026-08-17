# JSON -> CSV -> Amazon Redshift pipeline

This stage consumes the normalized JSON written by the site navigators. It
does not scrape pages. The complete AWS setup is in [`../db/README.md`](../db/README.md).

## Source lineage

The scraper JSON currently has no URL field, so `jsonToCsv.py` preserves the
page URL from the navigator filename and filtered sitemap:

| JSON directory | Redshift schema | Filename/manifest rule |
|---|---|---|
| `gsmarena.com` | `original` | `gsmarena__<page>.json` -> GSMArena `<page>` |
| `daraz.pk` | `daraz` | `daraz__<page>.json` -> `/products/<page>` |
| `mymobile.pk` | `mymobile` | `mymobile__<slug>.json` -> `/products/<slug>/` |
| `mega.pk` | `mega` | Must use the manifest because the numeric path ID is absent from the filename |
| `whatamobile.com.pk` | `whatamobile` | `whatamobile__<slug>.json` -> `/product/<slug>/` |
| `whatmobile.com.pk` | `whatmobile` | `whatmobile__<page>.json` -> `/<page>` |

Resolution order is: an explicit future `source_url`, a filtered manifest or
catalog record, then a deterministic filename rule. An ambiguous URL is sent
to `_manifest/errors.csv`; it is never guessed.

## Canonical release snapshots

GSMArena is the only release-date authority. For `original` records:

1. parse `Launch.Announced`;
2. if it cannot provide both a year and month, parse `Launch.Status`;
3. if that also fails, use the current UTC date.

`2024, July 03` becomes `data_snapshot=2024` and
`data_snapshot_detail=07-03`. `2024, December` becomes year `2024` and detail
`12`, preserving month-only precision. The CSV also contains
`snapshot_source` (`announced`, `status`, or `current_utc`) for auditability.

Marketplace CSV rows deliberately leave both snapshot columns blank and use
`snapshot_source=original_database`. During loading, Redshift first matches the
row to `original.central_info`, then copies both canonical values. A
marketplace file can never overwrite them.

## Create the hierarchy

From Windows PowerShell at the repository root:

```powershell
python .\filestorage\jsonToCsv.py
```

Useful controls:

```powershell
# One source
python .\filestorage\jsonToCsv.py --site gsmarena.com

# Deterministic final fallback; valid Announced/Status values still win
python .\filestorage\jsonToCsv.py --fallback-date 2026-08-17

# Stop at the first invalid file
python .\filestorage\jsonToCsv.py --strict

# Optionally archive the generated hierarchy
python .\filestorage\jsonToCsv.py `
  --archive-uri s3://my-private-bucket/landing/csv/run-2026-08-17
```

The output is:

```text
csvs/
|-- _manifest/
|   |-- manifest.json
|   |-- records.csv
|   `-- errors.csv
|-- original/
|   |-- records.csv              # Redshift COPY contract
|   |-- central_info.csv
|   |-- network.csv ... battery.csv
|   `-- raw_ingest.csv
`-- <marketplace>/
    |-- records.csv              # Redshift COPY contract
    |-- secondary_info.csv
    |-- central_info.csv         # unresolved until database matching
    |-- network.csv ... battery.csv
    `-- raw_ingest.csv
```

`record_key` is a stable SHA-256 of schema plus source URL. `file_sha256`
identifies the exact scraped payload. Database surrogate IDs are assigned by
the Redshift procedures, not inferred from CSV row order.

The per-table files are human-inspectable exports. The database loader consumes
only each schema's lossless `records.csv`.

## Validate and load Redshift

Install dependencies and validate without AWS access:

```powershell
python -m pip install -r .\requirements.txt
python .\filestorage\csvToDataBase.py --dry-run
```

After applying `db/schema_v1.sql` and `db/functions_v1.sql` and setting the
environment variables described in `db/README.md`:

```powershell
python .\filestorage\csvToDataBase.py
```

The loader uploads a private, uniquely named temporary S3 batch, runs COPY into
`staging.phone_records`, calls `etl.load_all()`, and removes only the objects it
uploaded. `SUPER` columns receive valid serialized JSON from the CSV fields.

Common controls:

```powershell
# Small end-to-end load
python .\filestorage\csvToDataBase.py --limit 100

# Selected inputs
python .\filestorage\csvToDataBase.py `
  --schema original --schema mega

# Retain the temporary S3 files while troubleshooting COPY
python .\filestorage\csvToDataBase.py --keep-s3-staging
```

Run only one loader at a time because v1 uses shared staging tables.

## Product matching

The first load must include GSMArena. Marketplace rows are accepted only when
they have either:

1. one exact, case-insensitive GSMArena name match; or
2. one reviewed mapping in a CSV containing
   `source_schema,source_url,product_id`.

```powershell
python .\filestorage\csvToDataBase.py `
  --master-map .\reviewed_matches.csv
```

Fuzzy matching is intentionally not automatic. An unmatched payload is retained
in `warehouse.raw_ingest` and explained in `warehouse.etl_rejects`, but is not
allowed into normalized source tables without a GSMArena product ID.

## Warehouse read surfaces

- `warehouse.current_listings`: one union of canonical and marketplace rows.
- `warehouse.price_history`: append-only observed prices; `observed_at` is the
  crawl/load timeline and must not be confused with product release dates.
- `analytics.product_bundle`: complete GSMArena specification record.
- `analytics.price_comparison`: latest seller prices by product.
- `analytics.site_price_summary`: aggregate source price statistics.
- `analytics.incomplete_records`: low-completeness raw inputs.
- `analytics.unmatched_records`: reviewed-mapping queue.

GSMArena price arrays do not identify currencies, so their history currency is
NULL. Marketplace prices are marked PKR.
