# Production backend contracts

The browser never calls Supabase or starts Python directly. Flask owns `/api/*` and delegates to `backend/control_api.py` / `backend/control_plane.py`.

Read endpoints:
- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/views`
- `GET /api/data/<products|listings|prices|discrepancies|site_summary>`

Operational metadata requires an authenticated operator session:
- `scrape_runs`
- `quality`
- `rejects`
- `/api/jobs*`

Write endpoints:
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `POST /api/operations`
- `POST /api/jobs/<id>/cancel`

`POST /api/operations` accepts only the allowlisted kinds implemented in `backend/control_plane.py`; arbitrary SQL, command strings, executable paths, and shell fragments are rejected by design.
