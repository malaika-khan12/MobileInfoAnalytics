"use client";

import { useEffect, useState } from "react";
import { AppShell, PageHeading } from "./app-shell";
import { SourceBars } from "./charts";
import { formatValue, liveApi, type JsonRecord } from "./live-api";
import { Icon } from "./icons";

type DashboardPayload = {
  ok: true;
  generated_at: string;
  metrics: { companies: number; products: number; listings: number; price_entries: number; avg_completeness_pct: number | null };
  sources: JsonRecord[];
  recent_products: JsonRecord[];
  price_spreads: JsonRecord[];
  recent_runs?: JsonRecord[];
};

function DataTable({ rows, columns }: { rows: JsonRecord[]; columns: string[] }) {
  if (!rows.length) return <div className="table-empty">No live rows returned.</div>;
  return <div className="compact-table-wrap"><table className="compact-table"><thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={String(row.product_id ?? row.run_id ?? index)}>{columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}</tr>)}</tbody></table></div>;
}

function Metric({ label, value, helper }: { label: string; value: unknown; helper: string }) {
  return <article className="metric-card"><div className="metric-top"><span>{label}</span></div><div className="metric-main"><strong>{formatValue(value)}</strong></div><div className="metric-foot"><span>{helper}</span></div></article>;
}

export function Dashboard() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  async function load() {
    setRefreshing(true); setError("");
    try { setData(await liveApi<DashboardPayload>("dashboard")); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setRefreshing(false); }
  }
  useEffect(() => { void load(); }, []);

  function exportSnapshot() {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "mobile-analytics-live-snapshot.json"; a.click(); URL.revokeObjectURL(url);
  }

  return <AppShell footer><div className="page-container dashboard-page">
    <PageHeading eyebrow="Production overview" title="Mobile Analytics dashboard" description="Current catalogue, market listings, source coverage, data quality, and ingestion activity from the finalized Supabase database." actions={<><button className="button button-secondary" type="button" onClick={() => void load()} disabled={refreshing}><Icon name="refresh" />{refreshing ? "Refreshing…" : "Refresh"}</button><button className="button button-primary" type="button" onClick={exportSnapshot} disabled={!data}><Icon name="download" />Export snapshot</button></>} />
    {error && <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Live connection error</span><h2>Dashboard unavailable</h2><p>{error}</p></div></div><div className="field-error">No fixture fallback is used. Fix the Control API/Supabase connection and retry.</div></section>}
    {!data && !error && <div className="loading-state"><img src="/loading.gif" alt="" /><span>Loading live database metrics…</span></div>}
    {data && <>
      <section className="metric-grid"><Metric label="Companies" value={data.metrics.companies} helper="catalog.companies" /><Metric label="Canonical products" value={data.metrics.products} helper="catalog.products" /><Metric label="Market listings" value={data.metrics.listings} helper="listings.market_listings" /><Metric label="Price entries" value={data.metrics.price_entries} helper="listings.listing_prices" /><Metric label="Mean completeness" value={data.metrics.avg_completeness_pct === null ? "—" : `${data.metrics.avg_completeness_pct}%`} helper="latest quality scores" /></section>
      <div className="analytics-grid analytics-grid-even"><section className="panel"><div className="panel-heading"><div><span className="panel-kicker">analytics.v_site_summary</span><h2>Listings by source</h2><p>Current listing counts from each populated source.</p></div></div><SourceBars rows={data.sources as { source_domain?: unknown; total_listings?: unknown }[]} /></section><section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Source quality</span><h2>Coverage and freshness</h2><p>Live distinct-product, completeness, and scrape timestamps.</p></div></div><DataTable rows={data.sources} columns={["source_domain","distinct_products_covered","total_listings","avg_data_completeness_pct","last_scraped_at"]} /></section></div>
      <div className="analytics-grid analytics-grid-even"><section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Canonical catalogue</span><h2>Recent products</h2><p>Newest product IDs currently visible in the canonical analytics view.</p></div></div><DataTable rows={data.recent_products} columns={["product_id","company_name","mobile_name","release_year","screen_technology","chipset_name","capacity_mah"]} /></section><section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Cross-source market</span><h2>Largest price spreads</h2><p>Current price ranges from analytics.v_price_comparison.</p></div></div><DataTable rows={data.price_spreads} columns={["product_id","company_name","mobile_name","currency_code","min_price","avg_price","max_price","price_spread","sources_count"]} /></section></div>
      {data.recent_runs && <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">metadata.scrape_runs</span><h2>Recent ingestion runs</h2><p>Authenticated server-side operational history from the database.</p></div></div><DataTable rows={data.recent_runs} columns={["run_id","source_domain","started_at","finished_at","records_processed","records_succeeded","records_failed","run_status"]} /></section>}
    </>}
  </div></AppShell>;
}
