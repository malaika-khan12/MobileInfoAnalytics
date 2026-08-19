# Production handoff

The TypeScript frontend now uses real MobileInfoAnalytics data and the existing Python pipeline through `backend/control_api.py` and `backend/control_plane.py`.

Rules for future work:
1. Do not reintroduce product, price, chart, event, run, or source-metric fixture data.
2. Keep Supabase secret keys and `MOBILE_ANALYTICS_ADMIN_TOKEN` out of browser bundles.
3. Preserve explicit operator login; never auto-inject an admin credential into every `/api/live/*` request.
4. Keep scraper/ETL execution allowlisted and argument-based—never accept arbitrary shell strings from the browser.
5. Keep raw operational metadata and job history operator-authenticated.
6. Preserve the finalized analytics-view contracts unless the database schema itself is deliberately versioned.
7. Use `db/frontend_api_grants.sql` after the finalized functions SQL.
8. On live-service failure, show an unavailable state; never synthesize replacement values.
