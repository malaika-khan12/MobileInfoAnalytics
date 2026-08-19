# Production frontend verification results

Verification performed against this packaged build on 2026-08-19.

## Passed in the build sandbox

- `python3 -m unittest discover -s frontend/tests -p 'test_*.py' -v`
  - 19 tests discovered.
  - 13 dependency-free production integration tests passed.
  - 6 Flask HTTP/session security tests were skipped only because Flask is not installed in the isolated build sandbox.
- `python3 -m py_compile backend/control_plane.py backend/control_api.py frontend/app.py frontend/streamlit_app.py`
  - Passed.
- `node --check frontend/static/js/app.js`
  - Passed.
- Runtime source scan found no fixture/dummy/mock product, price, metric, scraper-run, or event dataset.

## Tests included for the deployment environment

The six Flask tests cover:

- privileged operational metadata requires an operator session;
- operations require an operator session;
- login sets the named HttpOnly SameSite=Strict session cookie;
- unauthenticated health output hides filesystem paths and job history;
- unauthenticated dashboard output hides raw scrape-run history;
- authenticated dashboard output may include operational run history.

They run automatically after installing `frontend/requirements.txt`.

## Environment limitation

The sandbox cannot reach the Python package registry, so Flask/Waitress could not be installed here and those HTTP tests could not execute in this environment. This is not represented as a pass. Run the commands in `frontend/README.md` after dependency installation before deployment.

A live Supabase write/load was intentionally not executed from the packaging sandbox. The control-plane unit tests validate command construction and safety boundaries; your existing loader remains responsible for its own live dry-run, preflight, upload, retry, and post-load verification.
