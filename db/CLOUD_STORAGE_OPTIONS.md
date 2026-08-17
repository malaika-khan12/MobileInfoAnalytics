# Storage and database deployment options

The same v1 SQL and loader work on Supabase PostgreSQL, AWS PostgreSQL, and
Azure PostgreSQL. Raw JSON/CSV should be retained in object storage for large
crawls; PostgreSQL should hold curated current rows, product links, and price
history used by the application and BI layer.

## Recommended data layers

| Layer | Purpose | Supabase | AWS | Azure |
|---|---|---|---|---|
| Raw landing | Immutable JSON and crawl artifacts | Storage bucket | S3 | Blob Storage / ADLS Gen2 |
| Structured staging | Partitioned CSV/Parquet hierarchy | Storage bucket | S3 + Glue/Athena | ADLS + Data Factory/Synapse serverless |
| Operational warehouse | Normalized products, links, current prices | Supabase PostgreSQL | Aurora PostgreSQL or RDS PostgreSQL | Azure Database for PostgreSQL Flexible Server |
| Large analytical warehouse (optional) | Very large scans and BI aggregates | External warehouse | Redshift | Synapse / Fabric Warehouse |

Do not put cloud secrets in the repository. `boto3` uses the standard AWS SDK
credential chain. Azure uploads use `AZURE_STORAGE_CONNECTION_STRING`; a
managed-identity adaptation can be added when the job runs inside Azure.

## AWS

Archive the generated hierarchy to S3:

```powershell
python .\filestorage\jsonToCsv.py `
  --archive-uri s3://mobile-info-landing/csv/v1/run-2026-08-17
```

Load Aurora/RDS PostgreSQL after applying both v1 SQL files:

```powershell
$env:AWS_POSTGRES_URL = "postgresql://...?...sslmode=require"
python .\filestorage\csvToDataBase.py --target aws
```

For larger analytical workloads, catalog the per-table S3 hierarchy with AWS
Glue and query it with Athena, or transform it to Parquet before loading
Redshift. Keep `record_key`, `source_url`, `data_snapshot`, and `file_sha256`
through every transformation so rows remain traceable to the scrape.

## Azure

Archive to an Azure Blob container:

```powershell
$env:AZURE_STORAGE_CONNECTION_STRING = "..."
python .\filestorage\jsonToCsv.py `
  --archive-uri az://mobile-info-landing/csv/v1/run-2026-08-17
```

Load Azure Database for PostgreSQL Flexible Server after applying both v1 SQL
files:

```powershell
$env:AZURE_POSTGRES_URL = "postgresql://...?...sslmode=require"
python .\filestorage\csvToDataBase.py --target azure
```

ADLS Gen2 plus Synapse serverless is the natural extension when Power BI scans
become too large for the operational PostgreSQL database. Azure Data Factory or
Fabric pipelines can convert the normalized CSV tables to partitioned Parquet.

## Scale and retention guidance

- Keep raw crawl outputs immutable and partition object keys by
  `source/year/month/day/run`.
- Keep database source tables as the latest known listing state.
- Keep `warehouse.price_history` append-only for trend analysis.
- Treat `warehouse.raw_ingest` as an audit cache. At very large scale, retain
  the complete raw payload in object storage and apply a reviewed retention
  policy to older database copies only after object checksums are verified.
- Back up product links and canonical IDs before any matching-rule change.
- Convert CSV to compressed Parquet for long-term analytical storage; CSV is
  retained here because it is transparent, portable, and easy to validate.
- Use private networking, TLS verification, database connection pooling, and a
  least-privilege loader role in production.

The provider switch in `csvToDataBase.py` changes only connection-string
discovery because Supabase, Aurora/RDS PostgreSQL, and Azure PostgreSQL share
the same transactional schema. This keeps the ingestion contract portable and
avoids three divergent loaders.

