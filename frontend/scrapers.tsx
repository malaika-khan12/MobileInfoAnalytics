"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AppShell, Breadcrumbs, PageHeading, StatusBadge } from "./app-shell";
import { formatValue, liveApi, SOURCE_DEFINITIONS, type JsonRecord } from "./live-api";
import { Icon } from "./icons";
import type { ControlJob, ScrapeMode, SourceKey } from "./types";

type Health = { ok: true; database: { configured: boolean; reachable: boolean; error?: string }; scripts: Record<string, { path?: string; exists: boolean }> };
type Dashboard = { ok: true; sources: JsonRecord[] };
type AuthStatus = { ok:true; configured:boolean; authenticated:boolean };
type Jobs = { ok: true; jobs: ControlJob[] };
type Runs = { ok: true; rows: JsonRecord[] };

export function ScraperWorkspace({ sourceKey }: { sourceKey: SourceKey }) {
  const source = SOURCE_DEFINITIONS.find((item) => item.key === sourceKey) ?? SOURCE_DEFINITIONS[0];
  const [health, setHealth] = useState<Health | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [operator, setOperator] = useState(false);
  const [authConfigured, setAuthConfigured] = useState(false);
  const [jobs, setJobs] = useState<ControlJob[] | null>(null);
  const [runs, setRuns] = useState<JsonRecord[] | null>(null);
  const [mode, setMode] = useState<ScrapeMode>("range");
  const [minimum, setMinimum] = useState(1);
  const [maximum, setMaximum] = useState(5);
  const [urls, setUrls] = useState("");
  const [retries, setRetries] = useState(source.key === "gsmarena" ? 0 : 2);
  const [delayMin, setDelayMin] = useState(source.key === "gsmarena" ? 12 : 2);
  const [delayMax, setDelayMax] = useState(source.key === "gsmarena" ? 14 : 5);
  const [force, setForce] = useState(false);
  const [activeJob, setActiveJob] = useState<ControlJob | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    setError("");
    try {
      const [h,d,a] = await Promise.all([
        liveApi<Health>("health"),
        liveApi<Dashboard>("dashboard"),
        liveApi<AuthStatus>("auth/status"),
      ]);
      setHealth(h); setDashboard(d); setOperator(a.authenticated); setAuthConfigured(a.configured);
      if (a.authenticated) {
        const [j,r] = await Promise.all([liveApi<Jobs>("jobs?limit=12"), liveApi<Runs>("data/scrape_runs?limit=12")]);
        setJobs(j.jobs); setRuns(r.rows);
      } else {
        setJobs(null); setRuns(null); setActiveJob(null);
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }
  useEffect(() => { void load(); }, [source.key]);
  useEffect(() => {
    if (!operator || !activeJob || !["queued","running","cancelling"].includes(activeJob.status)) return;
    const timer = window.setInterval(async () => {
      try { const response = await liveApi<{ ok:true; job: ControlJob }>(`jobs/${activeJob.id}`); setActiveJob(response.job); if (!["queued","running","cancelling"].includes(response.job.status)) void load(); } catch { /* retain current state; next manual refresh can retry */ }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [operator, activeJob?.id, activeJob?.status]);

  const sourceRow = useMemo(() => dashboard?.sources.find((row) => row.source_domain === source.hostname), [dashboard, source.hostname]);
  const script = health?.scripts[`scraper:${source.key}`];
  const directUrlSupported = !["daraz", "whatmobile"].includes(source.key);

  async function submit() {
    if (!operator) { setError("Operator authentication is required before starting scraper jobs."); return; }
    setSubmitting(true); setError("");
    const payload: Record<string, unknown> = { kind:"scrape", source:source.key, mode, retries, delay_min:delayMin, delay_max:delayMax, force };
    if (mode === "range") Object.assign(payload, { minimum, maximum });
    if (mode === "single") payload.url = urls.trim();
    if (mode === "multiple") payload.urls = urls;
    try { const response = await liveApi<{ ok:true; job: ControlJob }>("operations", { method:"POST", body:JSON.stringify(payload) }); setActiveJob(response.job); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setSubmitting(false); }
  }

  async function cancel() {
    if (!operator || !activeJob) return;
    const response = await liveApi<{ ok:true; job: ControlJob }>(`jobs/${activeJob.id}/cancel`, { method:"POST", body:"{}" });
    setActiveJob(response.job);
  }

  const scriptDescription = !script ? "Loading script status…" : script.path ? script.path : script.exists ? "Script available; path is hidden until operator authentication." : "Required navigator script is missing.";

  return <AppShell footer><div className="page-container scraper-page">
    <Breadcrumbs items={[{ label:"Collection" }, { label:source.name }]} />
    <PageHeading eyebrow="Repository control plane" title="Scrapers" description="Run the existing Playwright navigator scripts through a server-side allowlist. No simulated progress or synthetic output is used." actions={<button className="button button-secondary" type="button" onClick={() => void load()}><Icon name="refresh" />Refresh</button>} />
    <div className="source-tabs">{SOURCE_DEFINITIONS.map((item) => <Link key={item.key} href={`/scrapers/${item.key}`} className={item.key === source.key ? "active" : ""}><strong>{item.name}</strong><small>{item.hostname}</small></Link>)}</div>
    {error && <div className="field-error">{error}</div>}
    {!operator && <div className="field-note">{authConfigured ? <>Authenticate in <Link href="/admin">Operations</Link> to start collection jobs and inspect job/run history.</> : <>Set <code>MOBILE_ANALYTICS_ADMIN_TOKEN</code> on the Control API before enabling collection operations.</>}</div>}
    <div className="scraper-page-grid"><div className="scraper-main-column">
      <section className="panel scraper-config-panel"><div className="panel-heading"><div><span className="panel-kicker">Actual navigator</span><h2>{source.name}</h2><p>{scriptDescription}</p></div><StatusBadge status={script?.exists ? "Ready" : "Missing"} /></div>
        <div className="scope-fields">
          <label className="field"><span>Mode</span><select value={mode} onChange={(event) => setMode(event.target.value as ScrapeMode)}><option value="range">Range</option><option value="full">Full resumable catalogue</option>{directUrlSupported && <><option value="single">Single URL</option><option value="multiple">Multiple URLs</option></>}</select></label>
          {mode === "range" && <div className="range-fields"><label className="field"><span>Minimum position</span><input type="number" min={1} value={minimum} onChange={(event) => setMinimum(Number(event.target.value))} /></label><label className="field"><span>Maximum position</span><input type="number" min={1} value={maximum} onChange={(event) => setMaximum(Number(event.target.value))} /></label></div>}
          {(mode === "single" || mode === "multiple") && <label className="field"><span>{mode === "single" ? "Product URL" : "Product URLs (one per line)"}</span><textarea rows={5} value={urls} onChange={(event) => setUrls(event.target.value)} placeholder={`https://${source.hostname}/…`} /></label>}
          <div className="range-fields"><label className="field"><span>Retries</span><input type="number" min={0} max={5} value={retries} onChange={(event) => setRetries(Number(event.target.value))} /></label><label className="field"><span>Minimum delay (seconds)</span><input type="number" min={source.key === "gsmarena" ? 10 : 0} step="0.5" value={delayMin} onChange={(event) => setDelayMin(Number(event.target.value))} /></label><label className="field"><span>Maximum delay (seconds)</span><input type="number" min={source.key === "gsmarena" ? 10 : 0} step="0.5" value={delayMax} onChange={(event) => setDelayMax(Number(event.target.value))} /></label></div>
          <label className="toggle-row"><span><strong>Overwrite valid existing outputs</strong><small>Passes `--force` to the navigator.</small></span><input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} /><i /></label>
        </div>
        <div className="run-actions"><p><Icon name="shield" />Writes stay server-side and use validated argument arrays, never browser shell text.</p><button className="button button-primary" type="button" disabled={!operator || submitting || !script?.exists || (!!activeJob && ["queued","running","cancelling"].includes(activeJob.status))} onClick={() => void submit()}><Icon name="play" />{submitting ? "Starting…" : "Run collection"}</button></div>
      </section>
      {operator && activeJob && <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Control-plane job</span><h2>{activeJob.id}</h2><p>{activeJob.label}</p></div><StatusBadge status={activeJob.status} /></div><p>Step {activeJob.current_step} of {activeJob.total_steps}</p><pre className="job-log">{activeJob.log_tail || "Waiting for log output…"}</pre>{["queued","running"].includes(activeJob.status) && <button className="button button-danger" type="button" onClick={() => void cancel()}><Icon name="square" />Cancel job</button>}</section>}
      <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">metadata.scrape_runs</span><h2>Database run history</h2><p>{operator ? "Actual ingestion run rows." : "Operational run metadata requires operator authentication."}</p></div></div>{operator ? <div className="compact-table-wrap"><table className="compact-table"><thead><tr>{["run_id","source_domain","started_at","records_processed","records_succeeded","records_failed","run_status"].map((c)=><th key={c}>{c.replaceAll("_"," ")}</th>)}</tr></thead><tbody>{(runs ?? []).map((row,index)=><tr key={String(row.run_id??index)}>{["run_id","source_domain","started_at","records_processed","records_succeeded","records_failed","run_status"].map((c)=><td key={c}>{formatValue(row[c])}</td>)}</tr>)}</tbody></table></div> : <div className="table-empty">Authenticate in Operations to view database run history.</div>}</section>
    </div><aside className="scraper-context"><section className="context-card"><span className="panel-kicker">Source row</span><h3>{source.name}</h3>{sourceRow ? <dl>{Object.entries(sourceRow).map(([key,value]) => <div key={key}><dt>{key.replaceAll("_"," ")}</dt><dd>{formatValue(value)}</dd></div>)}</dl> : <p>No analytics.v_site_summary row exists yet.</p>}</section><section className="context-card"><span className="panel-kicker">Local jobs</span>{!operator ? <p>Authenticate in Operations to view local job state.</p> : jobs?.length ? jobs.slice(0,8).map((job)=><button className="saved-query" key={job.id} onClick={()=>setActiveJob(job)}><span><strong>{job.id}</strong><small>{job.status}</small></span><Icon name="chevron-right" /></button>) : <p>No persisted control-plane jobs.</p>}</section></aside></div>
  </div></AppShell>;
}
