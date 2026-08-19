# Mobile Analytics — Flask / Streamlit production frontend

This variant stays within **Flask, Streamlit, HTML, CSS, D3.js and vanilla JavaScript**. It contains no product, price, run, chart, or event fixture dataset. If live services are unavailable, the UI shows an explicit error instead of substituting invented values.


> This package is intended to be overlaid onto the existing `MobileInfoAnalytics` repository so `backend/navigation_to_page/` and the three `filestorage/` pipeline scripts remain in their existing locations. If you run the frontend/control files from another directory, set `MOBILE_ANALYTICS_REPO_ROOT` to the real repository root before starting the server.

## Architecture

```text
Browser
  -> Flask /api/*
      -> backend/control_api.py
          -> backend/control_plane.py
              -> Supabase Data REST API
              -> backend/navigation_to_page/*.py
              -> filestorage/organise_with_llm.py
              -> filestorage/jsonToCsv.py
              -> filestorage/csvToDataBase.py
```

Database pages read the finalized analytics views:

- `analytics.v_canonical_products`
- `analytics.v_market_listings_full`
- `analytics.v_price_comparison`
- `analytics.v_spec_discrepancies`
- `analytics.v_site_summary`

Operational metadata (`metadata.scrape_runs`, `metadata.data_quality`, `metadata.etl_rejects`) is server-read and API access to those raw rows requires operator authentication.

## One-time database permission step

The finalized analytics views are created by the functions SQL after the broad grants in the schema SQL. Run this package's permission-only file **after** your finalized functions SQL:

```text
db/frontend_api_grants.sql
```

It grants the server role access to the already-created analytics views. It does not create/alter tables, views, functions, constraints, or data.

The Supabase Data API must expose the custom schemas used by the project (`catalog`, `specs`, `listings`, `metadata`, `staging`, and `analytics` as required by your finalized deployment).

## Required `.env`

Use the repository-root `.env`; do not copy secrets into frontend JavaScript.

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
SUPABASE_SECRET_KEY=sb_secret_...
TOGETHER_API_KEY=...

MOBILE_ANALYTICS_ADMIN_TOKEN=<long-random-operator-token>
FLASK_SECRET_KEY=<different-long-random-session-secret>

# Set to 1 behind HTTPS in production.
MOBILE_ANALYTICS_SECURE_COOKIES=1
```

The control plane prefers the server-only Supabase secret for server-side reads and never returns it to browser code.

## Install and run

From the MobileInfoAnalytics repository root:

```bash
python -m pip install -r frontend/requirements.txt
python -m playwright install chromium
python frontend/app.py
```

Use a production WSGI server outside development:

```bash
waitress-serve --listen=127.0.0.1:5000 frontend.app:app
```

Put HTTPS/reverse-proxy access control in front of any internet-facing deployment.

Streamlit remains a separate live analytics view:

```bash
streamlit run frontend/streamlit_app.py
```

## Governed operations

The Operations/Scrapers workspaces can invoke only known repository entry points. They never accept an arbitrary shell command or arbitrary browser SQL.

For this already-populated project, **Supabase preflight**, **Sync CSV → existing DB**, and **Full ETL sync** use the loader's explicit `--allow-existing` / `--reset-state` path where required. The uploader still performs its own CSV validation, custom-schema preflight, resumable state management, deterministic upserts, retries, and verification.

ETL/database jobs are exclusive: a write/transform/load job cannot overlap another active control-plane job. Multiple scraper jobs may overlap only when no ETL/database job is active.

Job metadata/logs persist under `filestorage/control_plane_jobs/`. Add that directory to the repository `.gitignore` if it is not already ignored.

## Tests

After dependencies are installed:

```bash
python -m unittest discover -s frontend/tests -v
node --check frontend/static/js/app.js
python -m py_compile frontend/app.py frontend/streamlit_app.py backend/control_api.py backend/control_plane.py
```

The HTTP tests automatically skip only when Flask itself is not installed; after `frontend/requirements.txt` is installed they execute normally.

## Verification report

See the package-root `TEST_RESULTS.md` for exactly what passed in the packaging sandbox and what must be rerun after Python dependencies are installed.
