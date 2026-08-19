# Mobile Analytics — Next.js / TypeScript production frontend

This is the React/TypeScript variant. It contains **no product, price, scraper-run, event, chart, or metric fixture dataset**. Browser components consume `/api/live/*`; that same-origin route proxies the Python MobileInfoAnalytics Control API.

## Architecture

```text
Browser (React)
  -> /api/live/* (Next server route)
      -> CONTROL_API_URL (Python Flask control service)
          -> backend/control_plane.py
              -> Supabase Data REST API
              -> backend/navigation_to_page/*.py
              -> filestorage/organise_with_llm.py
              -> filestorage/jsonToCsv.py
              -> filestorage/csvToDataBase.py
```

The proxy does **not** inject an administrator bearer token into ordinary browser requests. Operators authenticate explicitly on the Operations page; the Python API returns an HttpOnly SameSite session cookie, which the same-origin proxy forwards to the private control service.

## One-time database permission step

Run this file once **after** the finalized functions SQL:

```text
db/frontend_api_grants.sql
```

It is permission-only and gives the server role access to analytics views that are created after the schema SQL's earlier grants.

## Backend environment

The Python control service must execute against the **real MobileInfoAnalytics repository root**, because that is where the existing navigators, organiser, converter, loader, `.env`, and data folders live. If this TypeScript package is extracted into a separate directory, set:

```powershell
$env:MOBILE_ANALYTICS_REPO_ROOT="D:\Downloads\Repositories\MobileInfoAnalytics"
```

On Linux/WSL the equivalent is:

```bash
export MOBILE_ANALYTICS_REPO_ROOT=/mnt/d/Downloads/Repositories/MobileInfoAnalytics
```

If the package is overlaid directly onto the repository root, that variable is unnecessary. The Python control service reads the repository-root `.env`:

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
SUPABASE_SECRET_KEY=sb_secret_...
TOGETHER_API_KEY=...
MOBILE_ANALYTICS_ADMIN_TOKEN=<long-random-operator-token>
FLASK_SECRET_KEY=<different-long-random-session-secret>
MOBILE_ANALYTICS_SECURE_COOKIES=1
```

The Supabase Data API must expose the project's custom schemas used by the finalized loader/frontend.

Install the small control-service runtime if your root Python requirements do not already include it:

```bash
python -m pip install -r backend/requirements-control-api.txt
```

## Next runtime environment

```dotenv
CONTROL_API_URL=http://127.0.0.1:5050
```

Do not expose Supabase or operator secrets through `NEXT_PUBLIC_` variables.

## Run locally

If these files are overlaid into `MobileInfoAnalytics`, start the control API from that repository root. If the TypeScript package is kept separate, start it from the **TypeScript package directory** after setting `MOBILE_ANALYTICS_REPO_ROOT` to the real MobileInfoAnalytics repository:

```bash
python -m backend.control_api
```

For a production Python process, run the same module from the directory that contains this package's `backend/` folder:

```bash
waitress-serve --listen=127.0.0.1:5050 --call backend.control_api:create_app
```

Terminal 2, TypeScript frontend directory:

```bash
npm ci
npm run dev
```

For deployment, keep `CONTROL_API_URL` private/internal where possible and terminate HTTPS at the deployment edge/reverse proxy.

## Connected live surfaces

- `analytics.v_canonical_products`
- `analytics.v_market_listings_full`
- `analytics.v_price_comparison`
- `analytics.v_spec_discrepancies`
- `analytics.v_site_summary`
- authenticated operational reads from `metadata.scrape_runs`, `metadata.data_quality`, `metadata.etl_rejects`

Scraper/ETL actions call only allowlisted Python entry points with validated domains, sources, ranges, and arguments. Arbitrary browser SQL/shell execution is intentionally absent.

For this populated database, preflight/sync/full-pipeline actions use the resumable loader's explicit compatible-existing-database path. ETL/database jobs are serialized against active jobs; scraper jobs cannot start while an ETL/database operation is running.

## Tests

After Node/Python dependencies are installed:

```bash
npm run lint
npm run build
npm test
python -m unittest discover -s backend/tests -v
python -m py_compile backend/control_api.py backend/control_plane.py
```

A live Supabase connection is not required for compile/unit tests. Runtime pages show a genuine connection failure instead of falling back to invented values.

## Verification report

See `TEST_RESULTS.md` for exactly what passed in the packaging sandbox and what must be rerun after npm/Python dependencies are installed. No unavailable dependency check is claimed as passed.
