# Mobile Analytics frontend

This folder is the complete frontend implementation. It intentionally uses only Flask, Streamlit, HTML, CSS, D3.js, and vanilla JavaScript. There is no TypeScript, React, JSX, Vue, Svelte, Tailwind, Bootstrap, or frontend framework here.

## Run Flask

```bash
cd frontend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Open `http://127.0.0.1:5000`. Flask supports `/dashboard`, `/scrapers`, `/scrapers/<source>`, `/admin`, `/database`, and `/realtime`.

## Run Streamlit

```bash
cd frontend
streamlit run streamlit_app.py
```

Streamlit is a separate analytics entry point. It does not replace the Flask application.

## Structure

```text
frontend/
├── app.py                       Flask routes and template delivery
├── streamlit_app.py             Streamlit analytical view
├── requirements.txt             Python dependencies
├── templates/index.html         Shared semantic HTML shell
├── static/css/app.css           Design system and responsive layout
├── static/js/data.js            Deterministic fixtures
├── static/js/app.js             Views, interactions, and D3 charts
├── assets/                      Required supplied assets
├── BACKEND_CONTRACTS.md         Proposed production API contracts
└── HANDOFF_PROMPT.md            Detailed continuation instructions
```

## Implemented workspaces

- Dashboard: filters, dynamic KPIs, four analytical tabs, D3 line/donut/bar/scatter/heatmap charts, and JSON export.
- Scrapers: six sources, four scopes, four destinations, validation, whole-site restrictions, estimates, progress, cancellation, and JSON download.
- Admin: environments, schema browser, guarded SQL editor, presets, formatting, copy, mutation blocking, simulated execution, and results.
- Database: three governed views, optional two-table comparison, search, page-size control, CSV export, and record-lineage dialog.
- Real-time: live/pause state, KPIs, D3 throughput, anomalies, filters, source health, and deterministic event insertion.

## Product constraints

1. Preserve MyMobile, Daraz, GSMArena, Mega.pk, WhataMobile, and WhatMobile.
2. Page ranges stay within 1–15; multiple URL jobs accept 2–100 URLs.
3. Whole-site jobs cannot use display-only preview output.
4. The database explorer displays no more than two tables and 100 rows per table.
5. The SQL regex guard is only a client warning; production enforcement belongs on the server.
6. Fixture values must never be described as live production data.
7. Footer content remains limited to Admin and Real-time Analytics.
8. Do not add evasion, CAPTCHA bypass, proxy rotation, or rate-limit circumvention.

Read `BACKEND_CONTRACTS.md` before connecting backend responses, then use `HANDOFF_PROMPT.md` to continue consistently.
