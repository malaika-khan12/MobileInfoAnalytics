"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell, Breadcrumbs, PageHeading, StatusBadge } from "./app-shell";
import { formatValue, liveApi, type JsonRecord } from "./live-api";
import { Icon } from "./icons";
import type { ControlJob } from "./types";

type Health={ok:true;database:{configured:boolean;reachable:boolean;error?:string}};
type Dashboard={ok:true;sources:JsonRecord[];recent_runs:JsonRecord[]};
type AuthStatus={ok:true;configured:boolean;authenticated:boolean};
type Jobs={ok:true;jobs:ControlJob[]};
type Rejects={ok:true;rows:JsonRecord[]};

export function RealtimeAnalytics(){
  const [health,setHealth]=useState<Health|null>(null);
  const [dashboard,setDashboard]=useState<Dashboard|null>(null);
  const [operator,setOperator]=useState(false);
  const [jobs,setJobs]=useState<ControlJob[]|null>(null);
  const [rejects,setRejects]=useState<JsonRecord[]|null>(null);
  const [paused,setPaused]=useState(false);
  const [error,setError]=useState("");
  const [lastUpdated,setLastUpdated]=useState<Date|null>(null);

  async function load(){
    setError("");
    try{
      const [h,d,a]=await Promise.all([
        liveApi<Health>("health"),
        liveApi<Dashboard>("dashboard"),
        liveApi<AuthStatus>("auth/status"),
      ]);
      setHealth(h);setDashboard(d);setOperator(a.authenticated);
      if(a.authenticated){
        const [j,r]=await Promise.all([
          liveApi<Jobs>("jobs?limit=20"),
          liveApi<Rejects>("data/rejects?limit=20"),
        ]);
        setJobs(j.jobs);setRejects(r.rows);
      }else{
        setJobs(null);setRejects(null);
      }
      setLastUpdated(new Date());
    }catch(cause){setError(cause instanceof Error?cause.message:String(cause));}
  }

  useEffect(()=>{void load();},[]);
  useEffect(()=>{if(paused)return;const timer=window.setInterval(()=>void load(),5000);return()=>window.clearInterval(timer);},[paused]);
  const running=jobs?.filter(job=>["queued","running","cancelling"].includes(job.status))??[];

  return <AppShell footer><div className="page-container realtime-page">
    <Breadcrumbs items={[{label:"Operations"},{label:"Live status"}]} />
    <div className="realtime-title-row"><PageHeading eyebrow="Operational telemetry" title="Live production status" description="Five-second polling of Supabase state and persisted Control API jobs. This page never generates synthetic events." actions={<><button className={`button ${paused?"button-primary":"button-secondary"}`} type="button" onClick={()=>setPaused(current=>!current)}><Icon name={paused?"play":"pause"}/>{paused?"Resume polling":"Pause polling"}</button><button className="button button-secondary" type="button" onClick={()=>void load()}><Icon name="refresh"/>Refresh now</button></>}/><div className={`live-indicator ${paused?"is-paused":"is-live"}`}><span><i/>{paused?"PAUSED":"LIVE"}</span><small>{lastUpdated?`Updated ${lastUpdated.toLocaleTimeString()}`:"Waiting for first response"}</small></div></div>
    {error&&<div className="field-error">{error}. No synthetic fallback is displayed.</div>}
    {!operator&&<div className="field-note">Public analytics are visible. Authenticate in <Link href="/admin">Operations</Link> to view local jobs, ETL rejects, and other operational metadata.</div>}
    <section className="live-metric-grid">
      <article className="live-metric"><div className="live-metric-icon"><Icon name="database"/></div><div><span>Supabase</span><strong>{health?.database.reachable?"Reachable":"Unavailable"}</strong><small>Data REST API</small></div></article>
      <article className="live-metric"><div className="live-metric-icon"><Icon name="activity"/></div><div><span>Active local jobs</span><strong>{operator?running.length:"—"}</strong><small>{operator?"queued / running / cancelling":"operator access required"}</small></div></article>
      <article className="live-metric"><div className="live-metric-icon"><Icon name="globe"/></div><div><span>Sources with listings</span><strong>{dashboard?.sources.length??0}</strong><small>analytics.v_site_summary</small></div></article>
      <article className="live-metric"><div className="live-metric-icon"><Icon name="alert"/></div><div><span>Recent ETL rejects</span><strong>{operator?(rejects?.length??0):"—"}</strong><small>{operator?"latest API page":"operator access required"}</small></div></article>
    </section>
    <div className="realtime-grid">
      <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Control-plane execution</span><h2>Active jobs</h2><p>Actual subprocess state from filestorage/control_plane_jobs.</p></div><Link className="text-link" href="/admin">Open operations <Icon name="arrow-right"/></Link></div>{!operator?<div className="table-empty">Authenticate in Operations to view local job state.</div>:running.length?<div className="saved-query-list">{running.map(job=><div className="source-operations-row" key={job.id}><span><strong>{job.id}</strong></span><span>{job.kind}</span><span>{job.current_step}/{job.total_steps}</span><span>{job.started_at||job.created_at}</span><StatusBadge status={job.status}/></div>)}</div>:<div className="table-empty">No active jobs.</div>}</section>
      <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">analytics.v_site_summary</span><h2>Source freshness</h2><p>Current database coverage and latest scrape timestamps.</p></div></div><div className="source-operations-table"><div className="source-operations-head"><span>Source</span><span>Products</span><span>Listings</span><span>Completeness</span><span>Last scraped</span></div>{dashboard?.sources.map((row,index)=><div className="source-operations-row" key={String(row.source_domain??index)}><span><strong>{formatValue(row.source_domain)}</strong></span><span>{formatValue(row.distinct_products_covered)}</span><span>{formatValue(row.total_listings)}</span><span>{formatValue(row.avg_data_completeness_pct)}%</span><span>{formatValue(row.last_scraped_at)}</span></div>)}</div></section>
      <section className="panel live-feed-panel"><div className="panel-heading"><div><span className="panel-kicker">metadata.etl_rejects</span><h2>Recent rejects</h2><p>Persisted ETL failures requiring review.</p></div></div>{operator?<><div className="compact-table-wrap"><table className="compact-table"><thead><tr>{["reject_id","source_domain","source_file","reject_reason","rejected_at","resolved_at"].map(c=><th key={c}>{c.replaceAll("_"," ")}</th>)}</tr></thead><tbody>{(rejects??[]).map((row,index)=><tr key={String(row.reject_id??index)}>{["reject_id","source_domain","source_file","reject_reason","rejected_at","resolved_at"].map(c=><td key={c}>{formatValue(row[c])}</td>)}</tr>)}</tbody></table></div>{rejects?.length===0&&<div className="table-empty">No reject rows returned.</div>}</>:<div className="table-empty">Authenticate in Operations to view ETL rejects.</div>}</section>
      <section className="panel source-operations-panel"><div className="panel-heading"><div><span className="panel-kicker">metadata.scrape_runs</span><h2>Recent database runs</h2><p>{operator?"Latest ingestion run status.":"Operational run metadata requires operator authentication."}</p></div></div>{operator?<div className="compact-table-wrap"><table className="compact-table"><thead><tr>{["run_id","source_domain","started_at","records_processed","records_succeeded","records_failed","run_status"].map(c=><th key={c}>{c.replaceAll("_"," ")}</th>)}</tr></thead><tbody>{dashboard?.recent_runs.map((row,index)=><tr key={String(row.run_id??index)}>{["run_id","source_domain","started_at","records_processed","records_succeeded","records_failed","run_status"].map(c=><td key={c}>{formatValue(row[c])}</td>)}</tr>)}</tbody></table></div>:<div className="table-empty">Authenticate in Operations to inspect run history.</div>}</section>
    </div>
  </div></AppShell>;
}
