# Backend contract

Browser requests target `/api/live/<path>`. The Next server route forwards those requests to `CONTROL_API_URL/api/<path>` and forwards the HttpOnly operator session cookie when present.

Public/read-only surfaces include health, dashboard, analytics-view discovery, and public analytics data. Operator authentication is required for raw metadata, job history, job logs/cancellation, and all repository operations.

The Python service exposes only named operations implemented in `backend/control_plane.py`; browser-supplied executable paths, SQL strings, and shell command strings are not part of the contract.
