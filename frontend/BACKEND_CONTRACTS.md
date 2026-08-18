# Proposed backend contracts

These contracts are a production-oriented starting point for replacing `frontend/static/js/data.js`. They are not active endpoints in this frontend release. Keep them versioned under `/api/v1` so later schema changes are explicit.

## Shared response conventions

Successful list response:

```json
{
  "data": [],
  "meta": {
    "request_id": "req_01J...",
    "generated_at": "2026-08-18T01:45:00+05:00",
    "page": 1,
    "page_size": 25,
    "total_rows": 15284,
    "total_pages": 612
  }
}
```

Error response:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "End page must be between 1 and 15.",
    "field_errors": { "page_max": "Must be less than or equal to 15." },
    "request_id": "req_01J...",
    "retryable": false
  }
}
```

Every state-changing request should accept an `Idempotency-Key` header. Every response should return a request ID. Timestamps should be ISO 8601 with an explicit offset or UTC `Z` suffix.

## Identity and authorization

Minimum roles:

| Role | Catalogue | Scrapers | SQL | Alerts/configuration |
| --- | --- | --- | --- | --- |
| `viewer` | read/export | status only | none | none |
| `operator` | read/export | create/cancel approved jobs | approved read-only queries | acknowledge alerts |
| `analyst` | read/export | create approved jobs | read-only query console | save personal queries |
| `admin` | read/export | full job control | governed mutation flow | manage rules and environments |

Never infer admin capability from frontend route access. Enforce authorization in the API and database roles.

## Sources

`GET /api/v1/sources`

```json
{
  "data": [
    {
      "key": "gsmarena",
      "name": "GSMArena",
      "hostname": "gsmarena.com",
      "status": "rate_limited",
      "success_rate": 83.2,
      "median_response_ms": 1630,
      "known_records": 7215,
      "last_completed_at": "2026-08-18T01:21:00+05:00",
      "queue_depth": 7,
      "policy": {
        "max_concurrency": 2,
        "minimum_delay_ms": 1800,
        "robots_enforced": true,
        "full_site_authorization_required": true
      }
    }
  ]
}
```

Source statuses: `healthy`, `rate_limited`, `degraded`, `offline`, `disabled`.

## Scraper jobs

`POST /api/v1/scrape-jobs`

```json
{
  "source": "gsmarena",
  "scope": {
    "mode": "range",
    "page_min": 1,
    "page_max": 15,
    "urls": []
  },
  "destination": "json_and_database",
  "options": {
    "concurrency": 2,
    "minimum_delay_ms": 1800,
    "respect_robots": true,
    "deduplicate": true
  }
}
```

Scope rules:

- `single`: exactly one source-owned URL.
- `multiple`: 2–100 unique source-owned URLs.
- `range`: `page_min >= 1`, `page_max <= 15`, and `page_min <= page_max`.
- `full`: no URL or maximum page; requires explicit backend authorization.

Destinations:

- `preview`
- `json`
- `json_and_database`
- `database`

Reject `preview` for `full` jobs.

Creation response:

```json
{
  "data": {
    "id": "RUN-58421",
    "status": "queued",
    "source": "gsmarena",
    "estimated_pages": 15,
    "estimated_records": 294,
    "position": 4,
    "created_at": "2026-08-18T01:45:00+05:00"
  }
}
```

Other endpoints:

- `GET /api/v1/scrape-jobs?source=&status=&page=&page_size=`
- `GET /api/v1/scrape-jobs/{job_id}`
- `POST /api/v1/scrape-jobs/{job_id}/cancel`
- `POST /api/v1/scrape-jobs/{job_id}/retry`
- `GET /api/v1/scrape-jobs/{job_id}/preview`
- `GET /api/v1/scrape-jobs/{job_id}/artifact`

Job states: `queued`, `validating`, `running`, `normalizing`, `persisting`, `completed`, `partial`, `failed`, `cancelling`, `cancelled`.

The status payload should include counts for `pages_requested`, `pages_processed`, `records_discovered`, `records_validated`, `records_stored`, `duplicates_skipped`, `warnings`, and `errors`, plus a monotonic progress percentage.

## Catalogue

`GET /api/v1/catalogue/tables`

Return only tables exposed through the governed view layer. Do not expose every physical table automatically.

`GET /api/v1/catalogue/devices?page=1&page_size=25&search=&sort=id&direction=asc`

`GET /api/v1/catalogue/offers?page=1&page_size=25&search=&sort=updated_at&direction=desc`

`GET /api/v1/catalogue/scrape-runs?page=1&page_size=25&search=&sort=started_at&direction=desc`

Enforce `page_size <= 100` server-side. Allow only an explicit sort-column allowlist. Search parameters must be bound variables, never interpolated SQL.

`GET /api/v1/catalogue/{table}/{record_id}` should return normalized fields, raw-source references the caller may access, and a lineage array:

```json
{
  "data": {
    "record": {},
    "lineage": [
      { "stage": "collected", "status": "complete", "at": "2026-08-18T01:42:10+05:00" },
      { "stage": "normalized", "status": "complete", "at": "2026-08-18T01:42:11+05:00" },
      { "stage": "catalogue_upsert", "status": "complete", "at": "2026-08-18T01:42:12+05:00" }
    ]
  }
}
```

Export should be server-generated for large datasets:

`POST /api/v1/catalogue/exports` → returns an export job ID.

`GET /api/v1/catalogue/exports/{id}` → returns status and a short-lived download URL when ready.

## SQL administration

`POST /api/v1/admin/sql/validate`

```json
{
  "environment": "local",
  "statement": "SELECT ...",
  "read_only": true
}
```

Return parsed statement type, referenced schemas/tables, estimated risk, and an explain-plan summary. Use a real SQL parser. Regex is acceptable only as an extra client-side signal, never as the server security boundary.

`POST /api/v1/admin/sql/execute`

```json
{
  "environment": "local",
  "statement": "SELECT ...",
  "read_only": true,
  "row_limit": 100,
  "timeout_ms": 15000
}
```

Response:

```json
{
  "data": {
    "columns": [
      { "name": "brand", "database_type": "varchar", "nullable": false }
    ],
    "rows": [{ "brand": "Samsung" }],
    "row_count": 1,
    "truncated": false,
    "execution_ms": 184,
    "transaction_mode": "read_only"
  },
  "meta": { "request_id": "req_01J..." }
}
```

Production controls:

- separate read-only and write database credentials;
- transaction-level `READ ONLY` enforcement;
- statement timeouts;
- maximum returned rows and bytes;
- schema/table allowlists;
- audit log containing actor, environment, statement hash, result, duration, and request ID;
- no secrets or raw connection strings in the browser;
- an explicit two-person or policy approval flow for destructive statements where required.

## Dashboard aggregations

`GET /api/v1/analytics/market-overview?market=PK&source=all&period=30d`

Return KPI values, comparison deltas, freshness, and chart-ready series in one response to avoid a request waterfall.

`GET /api/v1/analytics/coverage-quality?...`

`GET /api/v1/analytics/pricing-value?...`

`GET /api/v1/analytics/relationships?...`

Keep raw analytical measures in the response and format PKR, percentages, and compact counts in the client. Every metric must include a human-readable definition and counting rule in API documentation.

## Live events

Preferred initial transport: Server-Sent Events because the browser only needs server-to-client updates.

`GET /api/v1/events/stream?source=all&type=all`

Event envelope:

```json
{
  "id": "evt_01J...",
  "sequence": 184221,
  "occurred_at": "2026-08-18T01:44:28+05:00",
  "source": "daraz",
  "type": "price_change",
  "severity": "positive",
  "entity": { "type": "offer", "id": "OFF-84921" },
  "title": "Galaxy S25 Ultra · 256 GB",
  "detail": "PKR 399,999 → PKR 389,999 · −2.5%",
  "payload": { "previous_price_pkr": 399999, "current_price_pkr": 389999 }
}
```

Support `Last-Event-ID` for reconnection. Retain a bounded replay window. Never rely on browser-generated timestamps or counters as canonical event values.

Additional endpoints:

- `GET /api/v1/operations/summary`
- `GET /api/v1/operations/source-health`
- `GET /api/v1/operations/anomalies?status=active`
- `POST /api/v1/operations/anomalies/{id}/acknowledge`
- `GET /api/v1/alert-rules`
- `POST /api/v1/alert-rules`
- `PATCH /api/v1/alert-rules/{id}`

## Frontend integration approach

1. Add a small typed API client with request ID propagation and normalized error handling.
2. Keep transport DTO types separate from view-model types.
3. Replace fixtures per workspace, not all at once.
4. Preserve current loading, empty, error, partial, and success UI states.
5. Use abort signals for route changes and explicit cancellation.
6. Add cache keys that include market, source, period, sort, filters, and page.
7. Do not silently fall back to fixture data in production. Surface a clear unavailable state.
8. Add contract tests using representative success and error payloads before enabling each live endpoint.
