"use client";

import { useEffect, useMemo, useState } from "react";
import { AppShell, Breadcrumbs, PageHeading } from "./app-shell";
import { formatValue, liveApi, type JsonRecord } from "./live-api";
import { Icon } from "./icons";

const VIEWS = [
  ["products", "Canonical products"],
  ["listings", "Market listings"],
  ["prices", "Price comparison"],
  ["discrepancies", "Spec discrepancies"],
  ["site_summary", "Site summary"],
  ["scrape_runs", "Scrape runs"],
  ["quality", "Data quality"],
  ["rejects", "ETL rejects"],
] as const;

const PRIVILEGED_VIEWS = new Set(["scrape_runs", "quality", "rejects"]);

type DataPayload = { ok: true; view: string; rows: JsonRecord[]; total: number; limit: number; offset: number };

export function DatabaseView() {
  const [view, setView] = useState("products");
  const [rows, setRows] = useState<JsonRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [operator, setOperator] = useState(false);

  async function load(nextOffset = offset, nextQuery = query, nextView = view, nextLimit = limit) {
    setLoading(true); setError("");
    try {
      const payload = await liveApi<DataPayload>(`data/${nextView}?limit=${nextLimit}&offset=${nextOffset}&q=${encodeURIComponent(nextQuery)}`);
      setRows(payload.rows); setTotal(payload.total); setOffset(payload.offset);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }

  useEffect(() => { void liveApi<{ok:true;authenticated:boolean}>("auth/status").then((auth) => setOperator(auth.authenticated)).catch(() => setOperator(false)); }, []);
  useEffect(() => { if (PRIVILEGED_VIEWS.has(view) && !operator) { setView("products"); return; } void load(0, "", view, limit); /* initial + view change */ }, [view, limit, operator]);
  useEffect(() => { const timer = window.setTimeout(() => void load(0, query, view, limit), 300); return () => window.clearTimeout(timer); }, [query]);

  const visibleViews = useMemo(() => VIEWS.filter(([key]) => operator || !PRIVILEGED_VIEWS.has(key)), [operator]);
  const columns = useMemo(() => rows.length ? Object.keys(rows[0]) : [], [rows]);
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(total, offset + limit);

  function exportCsv() {
    if (!rows.length) return;
    const keys = Object.keys(rows[0]);
    const csv = [keys.join(","), ...rows.map((row) => keys.map((key) => `"${formatValue(row[key]).replaceAll('"','""')}"`).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); const a = document.createElement("a"); a.href = url; a.download = `${view}.csv`; a.click(); URL.revokeObjectURL(url);
  }

  return <AppShell footer><div className="page-container database-page">
    <Breadcrumbs items={[{ label: "Data" }, { label: "Database view" }]} />
    <PageHeading eyebrow="Read-only live explorer" title="Database view" description={operator ? "Browse finalized analytics plus authenticated operational metadata through the server-side Supabase gateway." : "Browse finalized public analytics. Authenticate in Operations to inspect raw ETL metadata."} actions={<button className="button button-primary" type="button" onClick={exportCsv} disabled={!rows.length}><Icon name="download" />Export current rows</button>} />
    <section className="filter-toolbar">
      <label><span>View</span><select value={view} onChange={(event) => { setView(event.target.value); setOffset(0); }}>{visibleViews.map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="toolbar-search"><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search this view" /></label>
      <label><span>Rows</span><select value={limit} onChange={(event) => { setLimit(Number(event.target.value)); setOffset(0); }}><option>25</option><option>50</option><option>100</option></select></label>
    </section>
    <div className="database-summary"><span><strong>{total.toLocaleString()}</strong><small>live rows</small></span><span><strong>{rangeStart.toLocaleString()}–{rangeEnd.toLocaleString()}</strong><small>current page</small></span><span><strong>{VIEWS.find(([key]) => key === view)?.[1]}</strong><small>selected surface</small></span></div>
    {error && <section className="panel"><div className="field-error">{error}. No fixture fallback is used.</div></section>}
    <section className="panel database-table-panel"><div className="panel-heading"><div><span className="panel-kicker">Live API</span><h2>{VIEWS.find(([key]) => key === view)?.[1]}</h2><p>Maximum 100 rows per request. Click a row to inspect every returned field.</p></div>{loading && <span className="soft-badge">Loading…</span>}</div>
      {!loading && !rows.length ? <div className="table-empty">No rows returned.</div> : <div className="compact-table-wrap"><table className="compact-table"><thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={String(row.product_id ?? row.listing_id ?? row.run_id ?? row.score_id ?? row.reject_id ?? index)} onClick={() => setSelected(row)}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>)}</tbody></table></div>}
      <div className="pagination"><button className="button button-secondary" type="button" disabled={offset === 0 || loading} onClick={() => void load(Math.max(0, offset - limit))}>Previous</button><button className="button button-secondary" type="button" disabled={offset + limit >= total || loading} onClick={() => void load(offset + limit)}>Next</button></div>
    </section>
    {selected && <div className="modal-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setSelected(null)}><section className="record-drawer" role="dialog" aria-modal="true"><div className="record-drawer-head"><div><span className="panel-kicker">Live record</span><h2>Record inspector</h2></div><button className="icon-button" type="button" onClick={() => setSelected(null)}><Icon name="x" /></button></div><dl>{Object.entries(selected).map(([key,value]) => <div key={key}><dt>{key.replaceAll("_"," ")}</dt><dd>{formatValue(value)}</dd></div>)}</dl></section></div>}
  </div></AppShell>;
}
