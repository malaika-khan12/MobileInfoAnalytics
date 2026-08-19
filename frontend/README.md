# TypeScript frontend runtime

All React workspaces are production-connected through `frontend/live-api.ts` and the same-origin `/api/live/*` proxy. There is no market/product/pricing/job/event fixture store.

The proxy forwards the browser's HttpOnly operator session cookie to the private Python Control API. It does not inject an administrator token into ordinary requests. Supabase and repository-process access stay in Python server code.

Primary components:
- `dashboard.tsx` — live database metrics and source coverage
- `database-view.tsx` — bounded read-only explorer for finalized analytics views
- `scrapers.tsx` — validated source navigator jobs and persisted logs
- `admin.tsx` — explicit operator login and allowlisted ETL/database jobs
- `realtime.tsx` — polling of current database/control-plane state
