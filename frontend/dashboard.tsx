"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AppShell } from "./app-shell";
import { AdoptionRing, BarList, DiscrepancyHeatmap, DonutChart, PriceRanges, ReleaseYearBars, SourceCoverageChart, TechnologyScatter } from "./charts";
import { formatValue, liveApi, type JsonRecord } from "./live-api";
import { Icon } from "./icons";

type CountRow = { label?: unknown; count?: unknown };
type ProductInsights = {
  sample_size: number;
  company_counts: CountRow[];
  screen_counts: CountRow[];
  os_counts: CountRow[];
  release_year_counts: CountRow[];
  five_g_count: number;
  five_g_pct: number | null;
  wireless_charging_count: number;
  wireless_charging_pct: number | null;
  battery_avg_mah: number | null;
  battery_median_mah: number | null;
  scatter: JsonRecord[];
};
type DashboardPayload = {
  ok: true;
  generated_at: string;
  metrics: { companies: number; products: number; listings: number; price_entries: number; avg_completeness_pct: number | null };
  sources: JsonRecord[];
  recent_products: JsonRecord[];
  price_spreads: JsonRecord[];
  recent_runs?: JsonRecord[];
  product_insights: ProductInsights;
  discrepancy_insights: { sample_size: number; by_source: JsonRecord[] };
};

type DashboardTab = "overview" | "technology" | "pricing" | "quality";

function number(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function DataTable({ rows, columns, limit }: { rows: JsonRecord[]; columns: string[]; limit?: number }) {
  const visible = typeof limit === "number" ? rows.slice(0, limit) : rows;
  if (!visible.length) return <div className="table-empty">No live rows returned.</div>;
  return <div className="compact-table-wrap dashboard-table-wrap"><table className="compact-table"><thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{visible.map((row, index) => <tr key={String(row.product_id ?? row.run_id ?? row.source_domain ?? index)}>{columns.map((column) => <td key={column} title={formatValue(row[column])}>{formatValue(row[column])}</td>)}</tr>)}</tbody></table></div>;
}

function Metric({ label, value, helper, accent }: { label: string; value: unknown; helper: string; accent?: string }) {
  return <article className="metric-card intelligence-metric"><div className="metric-top"><span>{label}</span>{accent && <i>{accent}</i>}</div><div className="metric-main"><strong>{formatValue(value)}</strong></div><div className="metric-foot"><span>{helper}</span></div></article>;
}

function Panel({ kicker, title, copy, children, className = "" }: { kicker: string; title: string; copy: string; children: ReactNode; className?: string }) {
  return <section className={`panel intelligence-panel ${className}`}><div className="panel-heading"><div><span className="panel-kicker">{kicker}</span><h2>{title}</h2><p>{copy}</p></div></div>{children}</section>;
}

function SectionHeading({ index, title, copy }: { index: string; title: string; copy: string }) {
  return <div className="dashboard-section-heading"><span>{index}</span><div><h2>{title}</h2><p>{copy}</p></div></div>;
}

function insightText(data: DashboardPayload): ReactNode {
  const leader = [...data.sources].sort((a,b)=>number(b.total_listings)-number(a.total_listings))[0];
  const brand = data.product_insights.company_counts[0];
  const spread = data.price_spreads[0];
  return <>
    {leader && <><strong>{String(leader.source_domain)}</strong> leads source coverage with {number(leader.total_listings).toLocaleString()} listings</>}
    {leader && brand && <span> · </span>}
    {brand && <><strong>{String(brand.label)}</strong> is the most represented brand in the latest {data.product_insights.sample_size.toLocaleString()}-product sample</>}
    {spread && <><span> · </span>largest returned price spread: <strong>{formatValue(spread.price_spread)} {String(spread.currency_code ?? "")}</strong></>}
  </>;
}

export function Dashboard() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<DashboardTab>("overview");
  const [company, setCompany] = useState("All");
  const [screen, setScreen] = useState("All");
  const [network, setNetwork] = useState("All");

  async function load() {
    setRefreshing(true); setError("");
    try { setData(await liveApi<DashboardPayload>("dashboard")); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setRefreshing(false); }
  }
  useEffect(() => { void load(); }, []);

  const filteredScatter = useMemo(() => {
    if (!data) return [];
    return data.product_insights.scatter.filter((row) => {
      if (company !== "All" && String(row.company_name ?? "Unknown") !== company) return false;
      if (screen !== "All" && String(row.screen_technology ?? "Unknown") !== screen) return false;
      if (network === "5G only" && !Boolean(row.supports_5g)) return false;
      if (network === "Non-5G only" && Boolean(row.supports_5g)) return false;
      return true;
    });
  }, [data, company, screen, network]);

  function exportSnapshot() {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "mobile-analytics-live-snapshot.json"; a.click(); URL.revokeObjectURL(url);
  }

  const companies = data ? data.product_insights.company_counts.map((row)=>String(row.label ?? "Unknown")) : [];
  const screens = data ? data.product_insights.screen_counts.map((row)=>String(row.label ?? "Unknown")) : [];

  return <AppShell footer><div className="page-container dashboard-page intelligence-dashboard">
    <section className="intelligence-hero">
      <div className="intelligence-hero-copy"><p className="eyebrow">Production mobile-market analytics</p><h1>Mobile Market Intelligence</h1><p>Explore catalogue growth, source coverage, technology patterns, price dispersion, specification consistency, and ingestion freshness directly from the finalized Supabase database.</p><div className="hero-chip-row"><span>Live Supabase analytics</span><span>No fixture data</span><span>Cross-source comparison</span><span>Governed operations</span></div></div>
      <div className="intelligence-orbit" aria-hidden="true"><i/><strong>{data ? data.metrics.products.toLocaleString() : "—"}</strong><span>canonical products</span></div>
      <div className="hero-actions"><button className="button button-secondary" type="button" onClick={() => void load()} disabled={refreshing}><Icon name="refresh" />{refreshing ? "Refreshing…" : "Refresh"}</button><button className="button button-primary" type="button" onClick={exportSnapshot} disabled={!data}><Icon name="download" />Export snapshot</button></div>
    </section>

    {error && <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Live connection error</span><h2>Dashboard unavailable</h2><p>{error}</p></div></div><div className="field-error">No fixture fallback is used. Check the Control API, CONTROL_API_URL, and Supabase configuration, then retry.</div></section>}
    {!data && !error && <div className="loading-state"><img src="/loading.gif" alt="" /><span>Loading live database intelligence…</span></div>}

    {data && <>
      <section className="metric-grid intelligence-metrics"><Metric label="Companies" value={data.metrics.companies} helper="catalog.companies" accent="CATALOG"/><Metric label="Canonical products" value={data.metrics.products} helper="catalog.products" accent="CANONICAL"/><Metric label="Market listings" value={data.metrics.listings} helper={`${data.sources.length} populated sources`} accent="MARKET"/><Metric label="Price observations" value={data.metrics.price_entries} helper="listings.listing_prices" accent="PRICE"/><Metric label="Mean completeness" value={data.metrics.avg_completeness_pct === null ? "—" : `${data.metrics.avg_completeness_pct}%`} helper="latest quality scores" accent="QUALITY"/><Metric label="5G in sample" value={data.product_insights.five_g_pct === null ? "—" : `${data.product_insights.five_g_pct}%`} helper={`latest ${data.product_insights.sample_size.toLocaleString()} products`} accent="NETWORK"/></section>

      <div className="intelligence-insight"><span>◆</span><p>{insightText(data)}</p></div>
      <div className="sample-scope"><strong>Analytics scope.</strong> Population-level totals and source summaries are live database-wide values. Technology distributions use the latest <b>{data.product_insights.sample_size.toLocaleString()}</b> canonical products; discrepancy rates use the latest <b>{data.discrepancy_insights.sample_size.toLocaleString()}</b> comparison rows.</div>

      <div className="dashboard-tabs" role="tablist" aria-label="Dashboard analysis areas">
        {([['overview','Market overview'],['technology','Product technology'],['pricing','Price intelligence'],['quality','Quality & freshness']] as [DashboardTab,string][]).map(([key,text])=><button key={key} type="button" role="tab" aria-selected={tab===key} className={tab===key?'active':''} onClick={()=>setTab(key)}>{text}</button>)}
      </div>

      {tab === "overview" && <div className="dashboard-tab-panel">
        <SectionHeading index="01" title="Source footprint & quality" copy="Listing volume, distinct-product coverage, and average completeness show where the market dataset is deepest."/>
        <div className="analytics-grid dashboard-primary-grid"><Panel kicker="analytics.v_site_summary" title="Listings & completeness" copy="Bars use listing volume; the line uses the completeness scale."><SourceCoverageChart rows={data.sources}/></Panel><Panel kicker="Source detail" title="Coverage and freshness" copy="Current source-level totals and latest scrape timestamp."><DataTable rows={data.sources} columns={["source_domain","distinct_products_covered","total_listings","avg_data_completeness_pct","last_scraped_at"]}/></Panel></div>
        <SectionHeading index="02" title="Canonical catalogue composition" copy="Bounded, labelled sample analytics reveal brand, screen-technology, OS-family, and release-year patterns without pretending a sample is the full database."/>
        <div className="analytics-grid dashboard-three-grid"><Panel kicker="Brand mix" title="Most represented companies" copy="Top companies in the latest canonical-product sample."><BarList rows={data.product_insights.company_counts.slice(0,10)}/></Panel><Panel kicker="Display mix" title="Screen technology" copy="Relative screen-technology composition."><DonutChart rows={data.product_insights.screen_counts} center={`n=${data.product_insights.sample_size.toLocaleString()}`}/></Panel><Panel kicker="Release cadence" title="Release-year distribution" copy="Declared release years in the same sample."><ReleaseYearBars rows={data.product_insights.release_year_counts}/></Panel></div>
        <Panel kicker="Canonical catalogue" title="Recent products" copy="Newest product IDs currently visible in analytics.v_canonical_products."><DataTable rows={data.recent_products} columns={["company_name","mobile_name","release_year","supports_5g","screen_technology","refresh_rate_hz","operating_system","chipset_name","capacity_mah"]} limit={15}/></Panel>
      </div>}

      {tab === "technology" && <div className="dashboard-tab-panel">
        <div className="technology-toolbar"><div><span>Filter the bounded product sample</span><p>Filters affect the technology scatter and filtered-record table only.</p></div><label>Company<select value={company} onChange={(event)=>setCompany(event.target.value)}><option>All</option>{companies.map((item)=><option key={item}>{item}</option>)}</select></label><label>Screen<select value={screen} onChange={(event)=>setScreen(event.target.value)}><option>All</option>{screens.map((item)=><option key={item}>{item}</option>)}</select></label><label>5G<select value={network} onChange={(event)=>setNetwork(event.target.value)}><option>All</option><option>5G only</option><option>Non-5G only</option></select></label></div>
        <SectionHeading index="01" title="Technology landscape" copy="Battery capacity, display refresh rate, and pixel density show how sampled devices cluster by screen technology."/>
        <Panel kicker={`${filteredScatter.length.toLocaleString()} filtered products`} title="Battery × refresh-rate landscape" copy="Point size reflects pixel density; hover values are live canonical-product fields."><TechnologyScatter rows={filteredScatter}/></Panel>
        <div className="analytics-grid dashboard-three-grid"><Panel kicker="Adoption" title="5G support" copy="Share of the bounded canonical-product sample with 5G support."><AdoptionRing labelText="5G" value={data.product_insights.five_g_count} total={data.product_insights.sample_size}/></Panel><Panel kicker="Adoption" title="Wireless charging" copy="Share of the same sample reporting wireless charging."><AdoptionRing labelText="wireless" value={data.product_insights.wireless_charging_count} total={data.product_insights.sample_size}/></Panel><Panel kicker="Battery profile" title="Capacity statistics" copy="Central battery-capacity values from populated sample rows."><div className="mini-kpi-grid"><div><span>Average</span><strong>{data.product_insights.battery_avg_mah === null ? "—" : `${Math.round(data.product_insights.battery_avg_mah).toLocaleString()} mAh`}</strong></div><div><span>Median</span><strong>{data.product_insights.battery_median_mah === null ? "—" : `${Math.round(data.product_insights.battery_median_mah).toLocaleString()} mAh`}</strong></div><div><span>Sample</span><strong>{data.product_insights.sample_size.toLocaleString()}</strong></div></div></Panel></div>
        <div className="analytics-grid dashboard-primary-grid"><Panel kicker="OS mix" title="Operating-system families" copy="OS families in the latest canonical-product sample."><BarList rows={data.product_insights.os_counts}/></Panel><Panel kicker="Filtered sample" title="Product records" copy="The technology filters above apply to these live rows."><DataTable rows={filteredScatter} columns={["company_name","mobile_name","release_year","supports_5g","screen_technology","refresh_rate_hz","pixel_density_ppi","operating_system","capacity_mah","has_wireless_charging"]} limit={80}/></Panel></div>
      </div>}

      {tab === "pricing" && <div className="dashboard-tab-panel">
        <SectionHeading index="01" title="Cross-site price dispersion" copy="The range connects minimum and maximum observed price; the marker shows the mean for each returned comparison row."/>
        <Panel kicker="analytics.v_price_comparison" title="Largest returned price ranges" copy="Rows are ordered by price spread and remain currency-specific."><PriceRanges rows={data.price_spreads}/></Panel>
        <SectionHeading index="02" title="Price comparison detail" copy="Use the detailed rows to validate currencies, source counts, listing counts, and the spread behind each visual range."/>
        <Panel kicker="Market detail" title="Returned price-comparison rows" copy="No currency conversion is invented by the dashboard."><DataTable rows={data.price_spreads} columns={["company_name","mobile_name","currency_code","sources_count","total_listings","min_price","avg_price","max_price","price_spread"]}/></Panel>
      </div>}

      {tab === "quality" && <div className="dashboard-tab-panel">
        <SectionHeading index="01" title="Specification consistency" copy="Marketplace listing fields are compared with canonical specifications in a bounded cross-source discrepancy sample."/>
        <div className="analytics-grid dashboard-primary-grid"><Panel kicker="analytics.v_spec_discrepancies" title="Discrepancy matrix" copy="Battery, screen-technology, and refresh-rate mismatch rates by source."><DiscrepancyHeatmap rows={data.discrepancy_insights.by_source}/></Panel><Panel kicker="Freshness" title="Source scrape windows" copy="First/last timestamps and quality values from analytics.v_site_summary."><DataTable rows={data.sources} columns={["source_domain","total_listings","avg_data_completeness_pct","first_scraped_at","last_scraped_at"]}/></Panel></div>
        <SectionHeading index="02" title="Ingestion observability" copy="Operational run history is shown only when the Control API reports an authenticated operator session."/>
        {data.recent_runs ? <Panel kicker="metadata.scrape_runs" title="Recent ingestion runs" copy="Authenticated database run history."><DataTable rows={data.recent_runs} columns={["run_id","source_domain","started_at","finished_at","records_processed","records_succeeded","records_failed","run_status"]}/></Panel> : <div className="operator-note"><Icon name="shield"/><div><strong>Operational metadata is hidden</strong><p>Authenticate in the Admin panel to include recent scrape-run history in the dashboard payload.</p></div></div>}
      </div>}

      <div className="dashboard-generated">Live snapshot generated {new Date(data.generated_at).toLocaleString()} · no dummy-data fallback is implemented.</div>
    </>}
  </div></AppShell>;
}
