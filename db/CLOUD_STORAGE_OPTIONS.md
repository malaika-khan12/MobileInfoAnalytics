# Cloud storage decision: AWS

The project has selected Amazon Redshift rather than Supabase, Azure Database
for PostgreSQL, or an AWS PostgreSQL service. The maintained deployment path is:

```text
raw JSON archive in private S3
    -> normalized CSV staging in private S3
    -> Amazon Redshift COPY
    -> normalized schemas + analytical warehouse/views
    -> Power BI
```

See [`README.md`](README.md) for the complete Windows, S3, IAM, Redshift
Serverless, connection, loading, validation, and troubleshooting guide.

## Storage responsibilities

| Layer | AWS service | Retention |
|---|---|---|
| Raw scraped JSON | S3 immutable landing prefix | Long term; lifecycle to cheaper S3 classes |
| Generated CSV | Local workspace and optional S3 archive | Keep by crawl batch until verified |
| Temporary COPY batch | Private S3 staging prefix | Deleted by the loader after a successful/failed attempt unless `--keep-s3-staging` is used |
| Normalized current state | Redshift source schemas | Current canonical/listing rows |
| History and audit | Redshift `warehouse` schema | Price observations, raw audit rows, rejects, load summaries |
| BI contract | Redshift `analytics` views | Derived; recreate from SQL |

CSV is the transparent interchange format for v1. At larger scale, convert
archival data to partitioned Parquet while retaining `record_key`, `source_url`,
`file_sha256`, `data_snapshot`, and `data_snapshot_detail`. Redshift supports
Parquet/ORC COPY and `SERIALIZETOJSON` for nested values destined for `SUPER`.

Do not store credentials in JSON, CSV, SQL, `.env` files committed to Git, or
Power BI reports. Use AWS IAM for S3, session environment variables or a secret
manager for the database connection, private S3 buckets, TLS, and least-
privilege Redshift users.
