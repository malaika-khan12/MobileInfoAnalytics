# Continuation prompt for the next project chat

Copy everything below the divider into the next chat and attach the current project folder.

---

You are continuing the production frontend for **Mobile Analytics**, a governed data-collection and market-intelligence product for mobile-device specifications and retail listings. Do not rebuild it, change its stack, or reinterpret it as a generic dashboard. First read `README.md`, `frontend/README.md`, `frontend/BACKEND_CONTRACTS.md`, and this handoff completely. Run and inspect every route before editing.

## Mandatory technology constraint

The frontend must remain limited to Flask, Streamlit, HTML, CSS, D3.js, and vanilla JavaScript. Do not add TypeScript, React, JSX, Next.js, Vue, Svelte, Angular, jQuery, Tailwind, Bootstrap, another component framework, or another charting library. Do not create `.ts`, `.tsx`, or `.jsx` product files. Flask owns route/template delivery; HTML/CSS own structure and presentation; vanilla JavaScript owns routing and interaction; D3.js owns visualization; Streamlit remains a separate analytics entry point.

## Product and sources

Mobile Analytics collects authorized records from six sources, normalizes them into governed catalogue views, supports safe operational inspection, and provides historical and real-time analysis:

- MyMobile — `mymobile.pk`
- Daraz — `daraz.pk`
- GSMArena — `gsmarena.com`
- Mega.pk — `mega.pk`
- WhataMobile — `whatamobile.com.pk`
- WhatMobile — `whatmobile.com.pk`

The Flask routes are `/dashboard`, `/scrapers`, `/scrapers/<source>`, `/admin`, `/database`, and `/realtime`. Flask serves one semantic shell and vanilla JavaScript renders the current workspace while supporting history navigation.

## Current source structure

- `frontend/app.py`: Flask application, approved routes, and retained asset delivery.
- `frontend/templates/index.html`: shared navigation, accessibility skip link, quick-navigation dialog, toast region, theme control, and asset loading.
- `frontend/static/css/app.css`: tokens, components, workspace layouts, dark theme, breakpoints, focus, and reduced motion.
- `frontend/static/js/data.js`: deterministic fixtures for sources, devices, offers, jobs, trends, brands, and events.
- `frontend/static/js/app.js`: routing, templates, filters, exports, validation, simulations, inspectors, SQL protection, event streaming, and D3 charts.
- `frontend/streamlit_app.py`: separate Streamlit market-analysis view.
- `frontend/assets/`: brand mark, favicon, and loading animation.
- `frontend/BACKEND_CONTRACTS.md`: proposed production APIs.

If `app.js` becomes difficult to maintain, split it into native `.js` ES modules by domain. Do not introduce a framework. Keep one CSS design system unless plain-CSS modules become genuinely helpful.

## Completed experience

The shared shell has sticky responsive navigation, the supplied brand assets, persistent light/dark theme under `mobile-analytics-theme`, mobile navigation, Ctrl/Cmd+K quick navigation, keyboard focus, reduced-motion behavior, table overflow, dialogs, toasts, reusable panels/metrics/badges/forms, and footers only on Admin and Real-time.

The Dashboard labels fixtures honestly and provides market/source/period filters, reset, JSON export, four recomputed KPIs, and four tabs. Market overview has D3 growth lines, brand donut, price bands, and rankings. Coverage and quality has source success, completeness, and review queue. Pricing and value has median-price bars and movements. Relationship lab has a price-demand scatter plot, correlation heatmap, and non-causal interpretation.

Scrapers provide a workspace for every source with health, success, latency, record, and queue context. Scopes are single URL, 2–100 URLs, pages 1–15, and full catalogue. Destinations are preview JSON, stored JSON, JSON plus database, and database only. Preview is disabled for full catalogue. Controls include concurrency, delay, robots directives, deduplication, validation, estimates, staged progress, cancellation, completion counts, and download. These remain simulations until APIs replace them.

Admin includes Local PostgreSQL, Azure/Fabric, and AWS Redshift environments, connection status, allowlisted schema browser, read-only protection, presets, dark SQL editor, formatting/copy, result table, and history summary. The browser keyword guard is not security. The server must parse, authorize, enforce read-only transactions/timeouts/limits, separate credentials, and audit.

Database exposes Devices, Offers, and Scrape runs as governed views, with an optional second table, search, 25/50/100 page-size choices, CSV export, and a record-lineage dialog. Never expose arbitrary physical tables; never show more than two tables or 100 rows each.

Real-time includes LIVE/PAUSED state, stream control, KPIs, D3 throughput, anomalies, event/source filters, health, and deterministic insertion. Prefer Server-Sent Events with `Last-Event-ID` replay; use WebSockets only if bidirectional low-latency control becomes necessary.

Streamlit offers a separate six-source analytical view with period filter, KPIs, growth, brand share, source health, and fixture disclosure. It is not embedded in Flask.

## Visual direction

Preserve green `#09855b`, ink `#171a1f`, purple `#2e1b41`, blue `#5c8bc0`, light blue `#e0edfc`, pink `#f2e0e7`, orange `#ff9100`, and red `#c0392b`. The product is restrained, analytical, corporate, dense, and readable. Avoid generic SaaS gradients, huge marketing headings within operations, excessive glass effects, emoji icon systems, random KPI colors, oversized padding, unstructured charts, and inverted dark mode. New colors need a semantic role and dark equivalent.

## Non-negotiable correctness

1. Keep all six names and hostnames exactly.
2. Keep page ranges 1–15.
3. Keep multiple URL collection 2–100 and add hostname ownership validation for every line when integrating the backend.
4. Full catalogue cannot use display-only preview.
5. Database shows at most two tables and 100 rows per table.
6. Admin writes require server authorization and audit.
7. Footer stays limited to Admin and Real-time unless explicitly changed.
8. Preserve loading, empty, error, partial, cancellation, and success states.
9. State-changing APIs need idempotency and correlation IDs.
10. Backend collection enforces authorization, robots, pacing, backoff, and resumability.
11. Never implement CAPTCHA bypass, stealth, IP rotation, proxy evasion, or rate-limit circumvention.
12. Never call fixtures live.
13. Keep the approved stack intact.

## Backend sequence

Read `BACKEND_CONTRACTS.md`, then:

1. Add Flask configuration, auth/session roles, CSRF, structured errors, request IDs, and server logging.
2. Add sources and governed catalogue list/detail endpoints; replace only matching fixture reads after validation.
3. Add scrape creation, status, cancellation, retry, preview, and artifact endpoints while preserving every visual state. Prefer SSE; bounded polling is acceptable initially.
4. Add real-time SSE heartbeat, replay, reconnect backoff, and `Last-Event-ID`; remove deterministic insertion only after testing recovery.
5. Add SQL validation/execution with real server/database controls; retain the browser guard only as UX.
6. Add chart-ready dashboard aggregation endpoints and preserve D3 plus honest freshness labels.
7. Add saved queries, alert acknowledgements, preferences, and audit views.
8. Add Flask/API/DOM/accessibility tests and D3 visual regression coverage.

## Immediate improvements

- Vendor a pinned D3 v7 build under `frontend/static/vendor/` for offline deployment, preserving attribution and license.
- Split `app.js` into native modules during backend integration.
- Add hostname checks to every multiple-URL line.
- Make table sorting interactive and connect the 25/50/100 selection to pagination.
- Add D3 tooltips and accessible text summaries.
- Add proper Flask 404/500 templates while preserving recognized SPA routes.
- Add CSP, referrer policy, permissions policy, secure cookies, CSRF, and production headers.
- Make fixture/API mode an explicit environment flag.

The next milestone is done only when every direct route and history navigation works, mobile and dark mode remain usable, charts have accessible summaries, fixtures remain honest, backend controls are tested rather than assumed, the approved stack remains intact, and all three project documents match the code.
