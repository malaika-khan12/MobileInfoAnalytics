# Production handoff

This frontend has been converted from its original fixture-backed prototype into a live MobileInfoAnalytics control and analytics application.

Do not reintroduce dummy product, price, scraper-run, chart, event, or database rows. All user-visible values must originate from the finalized Supabase database or from persisted local control-plane job state.

The canonical integration points are `backend/control_api.py` and `backend/control_plane.py`. The ETL chain is the repository's existing organiser, JSON-to-CSV converter, and resumable Supabase loader. Scraper actions call the existing navigator scripts with validated argument arrays and never through a shell.

Before deployment, run `db/frontend_api_grants.sql` once after the finalized functions SQL, configure the `.env` values documented in `frontend/README.md`, install runtime dependencies, and execute the test commands in that README.
