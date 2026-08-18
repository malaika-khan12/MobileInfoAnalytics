# Supabase Functions & Analytics Views Guide (`functions_supabase.sql`)

This document provides a technical guide for the stored functions, procedures, and analytical views defined in [`db/functions_supabase.sql`](file:///d:/Downloads/Repositories/MobileInfoAnalytics/db/functions_supabase.sql).

---

## 1. Overview & Security Architecture

All database functions are designed for high-performance set-based processing in PostgreSQL / Supabase:

- **`SECURITY DEFINER` Execution**: Ingestion and catalog functions execute with database-owner permissions and an isolated `search_path` (`catalog, specs, listings, metadata, staging, analytics, public`) so automated ingestion scripts bypass RLS boundaries safely.
- **`WITH (security_invoker = true)` Views**: All 5 analytical views execute under the security context of the querying user/client, strictly obeying table-level RLS policies.

```mermaid
flowchart TD
    RawJSON["template_v2.json (from Scraper/LLM)"] --> IngestFn["etl.ingest_template_v2_json()"]
    
    subgraph "Product Linking Flow"
        IngestFn --> Slugify["catalog.slugify()"]
        Slugify --> Resolve["catalog.resolve_or_create_product()"]
        Resolve --> CheckProd{"Product Slug Exists?"}
        CheckProd -- Yes --> GetID["Return Existing product_id"]
        CheckProd -- No --> CheckAlias{"Alias Slug Exists?"}
        CheckAlias -- Yes --> GetAliasID["Return Aliased product_id"]
        CheckAlias -- No --> CreateProd["Insert catalog.products & Register Alias"]
        CreateProd --> GetNewID["Return New product_id"]
    end

    subgraph "Database Population"
        GetID & GetAliasID & GetNewID --> SaveListing["Insert/Update listings.market_listings"]
        SaveListing --> SavePrices["Parse & Insert listings.listing_prices"]
        SaveListing --> SaveSubSpecs["Insert 9 listings.listing_* Sub-Tables"]
        SaveListing --> CheckCanon{"Is GSMArena OR Canonical Empty?"}
        CheckCanon -- Yes --> SaveCanon["Upsert specs.product_specs & 9 spec_* Tables"]
        CheckCanon -- No --> SkipCanon["Preserve Existing Canonical Specs"]
        SaveListing --> Quality["Calculate & Log metadata.data_quality"]
    end
```

---

## 2. Core Functions & Procedures

### 2.1 `catalog.slugify(p_text TEXT) RETURNS TEXT`
- **Purpose**: Cleans arbitrary brand/model strings into standardized, lowercase, hyphen-separated slugs.
- **Rules**: Strips non-alphanumeric characters, converts whitespace/underscores to `-`, trims leading/trailing hyphens.
- **Example**: `'Xiaomi Redmi Note 14 (4G) - Global'` $\rightarrow$ `'xiaomi-redmi-note-14-4g-global'`.

---

### 2.2 `catalog.resolve_or_create_product(p_company_name, p_mobile_name, p_source_domain, p_source_title) RETURNS BIGINT`
- **Purpose**: The central disambiguation engine. Ensures that listings across Daraz, WhatMobile, Mega, and GSMArena link to the same central `product_id`.
- **Resolution Steps**:
  1. Checks `catalog.products` for exact `product_slug` match (`company-model`).
  2. Checks `catalog.product_aliases` for exact `alias_slug` match.
  3. If no match is found, creates the company (if new), creates a new row in `catalog.products`, registers initial aliases, and returns the new `product_id`.

---

### 2.3 `etl.ingest_template_v2_json(p_json, p_source_domain, p_source_file, p_scrape_run_id) RETURNS BIGINT`
- **Purpose**: Parses a single `template_v2.json` payload, linking it to the catalog and populating all listing and specification tables.
- **Operations Performed**:
  1. Calls `catalog.resolve_or_create_product()`.
  2. Calculates the next `instance_number` for the `(product_id, source_domain)` tuple.
  3. Inserts/updates `listings.market_listings`.
  4. Populates all 9 listing sub-tables (`listing_network`, `listing_body`, `listing_display`, `listing_platform`, `listing_memory`, `listing_camera_main`, `listing_camera_selfie`, `listing_connectivity`, `listing_battery`).
  5. Parses the `Price` array and generates structured rows in `listings.listing_prices` with currencies (`USD`, `EUR`, `GBP`, `PKR`).
  6. If `p_source_domain = 'gsmarena.com'` (or canonical specs are currently empty), populates `specs.product_specs` and all 9 `specs.spec_*` tables.
  7. Computes a completeness score (`completeness_pct`) and logs to `metadata.data_quality`.
  8. Catches any errors and writes the unparsed payload to `metadata.etl_rejects`.

---

### 2.4 `etl.process_staging_batch(p_batch_size, p_scrape_run_id)`
- **Purpose**: Iterates through rows in `staging.raw_json_records` where `status = 'pending'`, calling `etl.ingest_template_v2_json` on each and updating status to `'processed'` or `'failed'`.

---

## 3. Analytics Views Reference & Example Queries

### View 1: `analytics.v_canonical_products`
Flattened view of all mobile phones with complete GSMArena specifications.

```sql
-- Find all 5G phones with AMOLED display and battery capacity >= 5000 mAh
SELECT company_name, mobile_name, release_year, screen_technology, refresh_rate_hz, capacity_mah
FROM analytics.v_canonical_products
WHERE supports_5g = TRUE
  AND screen_technology = 'AMOLED'
  AND capacity_mah >= 5000
ORDER BY release_year DESC, mobile_name;
```

---

### View 2: `analytics.v_market_listings_full`
All individual scraped listings joined with company name, canonical product, and aggregated prices.

```sql
-- Inspect all listings for a specific model
SELECT source_domain, listing_title, instance_number, prices, screen_technology, capacity_mah
FROM analytics.v_market_listings_full
WHERE canonical_product_name ILIKE '%Redmi Note 14%'
ORDER BY source_domain, instance_number;
```

---

### View 3: `analytics.v_price_comparison`
Cross-site price comparison per phone, including minimum, average, maximum price, and price spread.

```sql
-- Find phones with the highest price spread across Pakistani marketplaces
SELECT company_name, mobile_name, currency_code, sources_count, min_price, max_price, price_spread, listings_detail
FROM analytics.v_price_comparison
WHERE currency_code = 'PKR'
  AND sources_count > 1
ORDER BY price_spread DESC
LIMIT 10;
```

---

### View 4: `analytics.v_spec_discrepancies`
Compares marketplace listings against GSMArena canonical specifications to highlight vendor discrepancies.

```sql
-- Identify listings reporting different battery or display specifications
SELECT company_name, mobile_name, source_domain, listing_title,
       canonical_battery_mah, listing_battery_mah,
       canonical_screen, listing_screen
FROM analytics.v_spec_discrepancies
WHERE battery_discrepancy = TRUE OR screen_discrepancy = TRUE;
```

---

### View 5: `analytics.v_site_summary`
Summary overview per website (product coverage, total listing count, data completeness percentage).

```sql
SELECT source_domain, distinct_products_covered, total_listings, avg_data_completeness_pct, first_scraped_at, last_scraped_at
FROM analytics.v_site_summary
ORDER BY total_listings DESC;
```

---

## 4. Python Integration Example

Here is how you can invoke the ingestion function directly from Python:

```python
import json
import psycopg2
from psycopg2.extras import Json

# Connect to Supabase PostgreSQL
conn = psycopg2.connect("postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres")
cursor = conn.cursor()

# Load your template_v2 JSON file
with open("filestorage/mobiles_organised/gsmarena__xiaomi_redmi_note_14_4g.json", "r", encoding="utf-8") as f:
    mobile_data = json.load(f)

# Execute ingestion
cursor.execute("""
    SELECT etl.ingest_template_v2_json(
        p_json := %s,
        p_source_domain := %s,
        p_source_file := %s
    );
""", (Json(mobile_data), "gsmarena.com", "gsmarena__xiaomi_redmi_note_14_4g.json"))

listing_id = cursor.fetchone()[0]
conn.commit()

print(f"Successfully ingested listing ID: {listing_id}")
cursor.close()
conn.close()
```
