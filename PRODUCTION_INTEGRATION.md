# MobileInfoAnalytics production integration summary

- Fixture-backed runtime state removed.
- Finalized Supabase analytics views wired to live dashboard/database pages.
- Server-only Supabase credential handling added.
- Existing scraper navigator scripts wired through validated subprocess argument arrays.
- LLM organiser, JSON-to-CSV conversion, CSV dry-run, preflight, resumable upload, and full ETL sync wired to the Operations UI.
- Persistent job logs/status/cancellation added.
- Operator authentication, HttpOnly/SameSite sessions, metadata authorization, security headers, source/site allowlists, and ETL concurrency guards added.
- Existing populated database workflow uses the loader's explicit compatible replay flags.
- Post-functions analytics-view grant script added without changing finalized schema shape.
- Flask/vanilla-JS unit/static tests included.
