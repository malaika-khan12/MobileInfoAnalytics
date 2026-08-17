# Amazon Redshift setup and loading guide

This project uses Amazon Redshift as its analytical database and Amazon S3 as
the bulk-load landing area. For a first deployment, use **Redshift Serverless**:
AWS manages the warehouse capacity while the repository keeps the same SQL and
Python interface as a provisioned Redshift cluster.

The data flow is:

```text
scraped JSON
    -> filestorage/jsonToCsv.py
    -> local <schema>/records.csv
    -> temporary private S3 objects
    -> COPY into staging.phone_records
    -> CALL etl.load_all()
    -> normalized source schemas + warehouse facts + analytics views
```

GSMArena is the master product catalog. Marketplace records are loaded into a
normalized source schema only after they match one row in
`original.central_info`. Their `data_snapshot` and `data_snapshot_detail` are
copied from that GSMArena row; marketplace JSON is never allowed to set either
field.

## 1. Create the AWS resources

Keep all resources in one AWS Region.

1. Create a private S3 bucket, for example
   `mobile-info-analytics-<account-id>`. Keep **Block all public access** on.
   A prefix such as `redshift-stage/` is enough; do not create folders
   manually.
2. In Amazon Redshift, choose **Redshift Serverless**, then create a namespace
   and workgroup. A database named `mobileinfo` is a clear default.
3. Save the workgroup endpoint, database name, administrator user, and
   password in a password manager. The normal Redshift port is `5439`.
4. Attach an IAM role to the Redshift namespace that can read only the chosen
   S3 bucket/prefix. The loader passes this role ARN to `COPY`.
5. Give the Windows AWS identity running the Python loader permission to upload
   and delete objects under that same prefix. These are two distinct access
   paths: the Windows identity writes the files; the Redshift IAM role reads
   them.

AWS references:

- [Create Serverless workgroups and namespaces](https://docs.aws.amazon.com/redshift/latest/mgmt/serverless-workgroup-namespace.html)
- [Connect to Redshift Serverless](https://docs.aws.amazon.com/redshift/latest/mgmt/serverless-connecting.html)
- [Authorize COPY from S3](https://docs.aws.amazon.com/redshift/latest/dg/copy-parameters-authorization.html)
- [COPY command](https://docs.aws.amazon.com/redshift/latest/dg/r_COPY.html)

### Network access from Windows

The AWS Query Editor runs inside AWS and does not require opening Redshift to
your laptop. The Python loader does require network access to the endpoint.
For a local development workgroup, either:

- use a publicly accessible endpoint whose security group permits TCP `5439`
  from **your current public IP only**, or
- keep it private and connect through your organization's VPN/bastion.

Never permit `0.0.0.0/0` on port 5439. TLS remains enabled by the Python
connector.

## 2. Install the local tools on Windows

From PowerShell in the repository root:

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\requirements.txt
```

Install [AWS CLI v2 for Windows](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
if `aws --version` is not already available.

Configure an AWS identity for `boto3`. AWS IAM Identity Center is preferred
when your account supports it:

```powershell
aws configure sso
aws sso login
```

For a small personal account, `aws configure` also works. Do not put AWS keys,
database passwords, or connection strings in this repository.

## 3. Create the database objects

Open **Amazon Redshift Query Editor v2**, connect to `mobileinfo`, and run the
files in this exact order:

1. `db/schema_v1.sql`
2. `db/functions_v1.sql`

The first file creates the normalized schemas, COPY staging tables, durable
landing tables, and price facts. The second creates set-based load procedures
and BI views. Both files are Redshift SQL; they are not Supabase/PostgreSQL
migrations.

Redshift does not enforce primary, unique, and foreign-key constraints in the
same way as an operational PostgreSQL database. They are useful planner
metadata, while the ETL procedures perform actual de-duplication and matching.
See [Redshift constraint behavior](https://docs.aws.amazon.com/redshift/latest/dg/t_Defining_constraints.html).

Verify initialization:

```sql
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema IN ('original', 'staging', 'warehouse')
ORDER BY 1, 2;

SELECT * FROM svv_procedures
WHERE procedure_schema = 'etl'
ORDER BY procedure_name;
```

## 4. Understand the release-date contract

For GSMArena JSON only, `jsonToCsv.py` applies this order:

1. parse `Launch.Announced`;
2. if that cannot supply a year and month, parse `Launch.Status`;
3. if both fail, use the current UTC date.

Examples:

| GSMArena text | `data_snapshot` | `data_snapshot_detail` |
|---|---:|---|
| `2024, July 03` | `2024` | `07-03` |
| `2024, December` | `2024` | `12` |
| `Available. Released 2024, July` | `2024` | `07` |

The two columns form one value. A bad day does not get combined with a year
from a different source. Marketplace CSV rows contain blank values and the
marker `original_database`; `etl.load_source` obtains both columns through the
matched GSMArena `product_id`.

## 5. Build and validate CSVs

Creating CSVs is a separate, repeatable step:

```powershell
python .\filestorage\jsonToCsv.py
python .\filestorage\csvToDataBase.py --dry-run
```

To make fallback behavior deterministic for an imported archive:

```powershell
python .\filestorage\jsonToCsv.py --fallback-date 2026-08-17
```

`--fallback-date` is used only when both GSMArena launch fields fail. It does
not override valid dates.

## 6. Connect and load

Set session-only PowerShell environment variables. Replace every example value:

```powershell
$env:AWS_REGION = "us-east-1"
$env:REDSHIFT_HOST = "<workgroup-name>.<account-id>.<region>.redshift-serverless.amazonaws.com"
$env:REDSHIFT_PORT = "5439"
$env:REDSHIFT_DATABASE = "mobileinfo"
$env:REDSHIFT_USER = "admin"
$env:REDSHIFT_PASSWORD = "use-your-password-manager"
$env:REDSHIFT_S3_URI = "s3://mobile-info-analytics-<account-id>/redshift-stage"
$env:REDSHIFT_IAM_ROLE = "arn:aws:iam::<account-id>:role/MobileInfoRedshiftCopyRole"

python .\filestorage\csvToDataBase.py --dry-run
python .\filestorage\csvToDataBase.py
```

The real run performs these operations:

1. validates every selected local row;
2. writes a bounded temporary batch locally (also implementing `--limit`);
3. uploads that batch beneath a unique S3 `loads/<token>/` prefix;
4. truncates the two shared staging tables;
5. uses `COPY` for each source and calls `etl.load_all()` in one transaction;
6. deletes only the exact temporary objects it uploaded.

Use `--keep-s3-staging` when investigating a load. Run only one loader against
this v1 staging schema at a time.

Useful small and selective loads:

```powershell
python .\filestorage\csvToDataBase.py --limit 100

python .\filestorage\csvToDataBase.py `
  --schema original `
  --schema mega
```

Load `original` before marketplaces on the first run. On later runs,
`etl.load_all()` always processes staged GSMArena rows first.

## 7. Product matching

The safe automatic rule is an exact, case-insensitive name match to GSMArena.
Fuzzy matching is deliberately not automatic. Provide reviewed exceptions as:

```csv
source_schema,source_url,product_id
mega,https://www.mega.pk/mobiles_products/23647/Example.html,123
```

Then load with:

```powershell
python .\filestorage\csvToDataBase.py `
  --master-map .\reviewed_matches.csv
```

An unmatched row is preserved in `warehouse.raw_ingest` and recorded in
`warehouse.etl_rejects`, but it is not inserted into a marketplace schema. This
keeps GSMArena as the source of truth and prevents an invented `product_id`.

## 8. Verify and query

```sql
SELECT COUNT(*) FROM original.central_info;
SELECT source_schema, COUNT(*)
FROM warehouse.current_listings
GROUP BY 1 ORDER BY 1;

SELECT * FROM analytics.unmatched_records
ORDER BY rejected_at DESC LIMIT 100;

SELECT * FROM analytics.price_comparison
WHERE product_id = 123
ORDER BY amount;

SELECT * FROM analytics.site_price_summary
ORDER BY source_schema;
```

`warehouse.price_history.observed_at` records when a price file entered the
warehouse. The two `data_snapshot*` columns remain the GSMArena release date;
they are not reused as crawl timestamps.

## 9. Power BI

Use Power BI's Amazon Redshift connector with the same host, port, database,
and a read-only database user. Prefer the `analytics.*` views instead of
importing staging or raw payload tables. Start with Import mode; move to
DirectQuery only when the model size and refresh requirements justify it.

## 10. Operations and cost safety

- Set a Redshift Serverless usage limit and a billing alarm before mass loads.
- Keep S3 and Redshift in the same Region.
- Add an S3 lifecycle rule for abandoned `redshift-stage/loads/` objects.
- Keep raw scraped JSON in a separate immutable S3 landing prefix; the loader's
  temporary COPY files are not your archive.
- Use separate least-privilege users for schema administration, ETL, and BI.
- Regularly review `warehouse.etl_rejects` before changing matching rules.
- Convert long-term CSV archives to Parquet when scan cost becomes material;
  Redshift supports loading nested columnar data into `SUPER` with
  `SERIALIZETOJSON`.

For Python connection options, see the official
[Amazon Redshift Python connector guide](https://docs.aws.amazon.com/redshift/latest/mgmt/python-redshift-driver.html).

## Troubleshooting

**Connection timeout** — confirm endpoint accessibility, the security-group
source IP, port 5439, and that the workgroup is available.

**AccessDenied during upload** — the Windows AWS identity lacks `s3:PutObject`
for the staging prefix.

**COPY says AccessDenied** — the IAM role named by `REDSHIFT_IAM_ROLE` is not
attached to Redshift or lacks `s3:GetObject`/`s3:ListBucket` for that prefix.

**COPY conversion failure** — first run the local `--dry-run`, then inspect:

```sql
SELECT * FROM sys_load_error_detail
ORDER BY start_time DESC LIMIT 50;
```

**Rows appear only in rejects** — load GSMArena first, then review
`analytics.unmatched_records` and prepare an explicit master map.

**Schema changed but tables did not** — `CREATE TABLE IF NOT EXISTS` does not
alter an existing table. For a fresh development database, recreate the
database and rerun both SQL files. For production, write a versioned migration
instead of dropping populated tables.
