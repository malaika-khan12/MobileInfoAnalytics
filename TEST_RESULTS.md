# Production frontend verification results

Verification performed against this packaged build on 2026-08-19.

## Passed in the build sandbox

- `python3 -m unittest discover -s backend/tests -p 'test_*.py' -v`
  - 19 tests discovered.
  - 13 dependency-free production integration tests passed.
  - 6 Flask HTTP/session security tests were skipped only because Flask is not installed in the isolated build sandbox.
- `python3 -m py_compile backend/control_plane.py backend/control_api.py`
  - Passed.
- TypeScript parser validation using TypeScript 5.8.3:
  - 25 TypeScript/TSX files parsed; 0 syntax diagnostics across the packaged application.
- Relative local-import resolution scan:
  - Passed; no packaged TypeScript module points at a removed/missing relative file.
- Offline package-lock-only reconciliation after removing the unused Drizzle/D1 scaffold:
  - Passed; `package.json` and `package-lock.json` remain synchronized.
- Stubbed semantic TypeScript check across the production components, proxy route, and Next config:
  - Passed. The stubs replace unavailable React/Next type packages only; local component/data-flow types were still checked.
- Runtime source scan found no fixture/dummy/mock product, price, metric, scraper-run, or event dataset.

## Tests included for the deployment environment

The six Flask tests cover privileged metadata authorization, write authorization, session-cookie security, unauthenticated health redaction, and dashboard operational-history redaction.

The frontend also includes `tests/rendered-html.test.mjs`, which exercises the primary rendered production routes after a successful build.

## Environment limitation

The build sandbox cannot reach the npm registry and does not contain the required npm tarballs in its offline cache. Therefore `npm ci`, the full Next/Vinext production build, ESLint, and the rendered-HTML test could not be executed here. This is not represented as a pass.

Before deployment, from this frontend directory run:

```bash
npm ci
npm run lint
npm run build
npm test
```

The Python package registry is likewise unreachable in the sandbox, so the six Flask HTTP tests could not execute here. Install `backend/requirements-control-api.txt` and rerun the Python test suite before deployment.

A live Supabase write/load was intentionally not executed from the packaging sandbox. The existing loader remains responsible for live dry-run, preflight, resumable upload, retries, and post-load verification.
