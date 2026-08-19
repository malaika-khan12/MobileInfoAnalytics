"use client";

import { useEffect, useState, type FormEvent } from "react";
import { AppShell, Breadcrumbs, PageHeading, StatusBadge } from "./app-shell";
import { liveApi } from "./live-api";
import { Icon } from "./icons";
import type { ControlJob } from "./types";

type Health = { ok:true; repo_root?:string; configured_repo_root?:string|null; configured_repo_root_exists?:boolean|null; repo_root_warning?:string|null; session_cookie_secure?:boolean; security_warnings?:string[]; database:{configured:boolean;reachable:boolean;error?:string}; scripts:Record<string,{path?:string;exists:boolean}>; jobs?:ControlJob[] };
type Auth = { ok:true; authenticated:boolean; configured:boolean };
type Jobs = { ok:true; jobs:ControlJob[] };

const OPERATIONS = [
  { kind:"organise", label:"Organise with LLM", description:"Run filestorage/organise_with_llm.py against source JSON.", dangerous:false },
  { kind:"convert", label:"JSON → CSV", description:"Run filestorage/jsonToCsv.py and regenerate the finalized CSV hierarchy.", dangerous:false },
  { kind:"upload-dry-run", label:"Validate 28 tables", description:"Run csvToDataBase.py --dry-run. No database write occurs.", dangerous:false },
  { kind:"upload-preflight", label:"Supabase preflight", description:"Validate credentials, exposed schemas, target counts, and refresh loader state for the populated project. No database rows are uploaded.", dangerous:false, existing:true },
  { kind:"upload-resume", label:"Resume interrupted upload", description:"Continue the loader from its persisted database_upload_state.json without resetting progress.", dangerous:true },
  { kind:"upload", label:"Sync CSV → existing DB", description:"Reset loader state and idempotently replay the current CSV hierarchy into the populated project database.", dangerous:true, existing:true },
  { kind:"full-pipeline", label:"Full ETL sync", description:"Organise → convert → dry-run → preflight → idempotent sync into the populated project database.", dangerous:true, existing:true },
] as const;

export function AdminPanel() {
  const [health,setHealth]=useState<Health|null>(null);
  const [auth,setAuth]=useState<Auth|null>(null);
  const [jobs,setJobs]=useState<ControlJob[]>([]);
  const [active,setActive]=useState<ControlJob|null>(null);
  const [token,setToken]=useState("");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState("");

  async function load(){
    setError("");
    try{
      const [h,a]=await Promise.all([liveApi<Health>("health"),liveApi<Auth>("auth/status")]);
      setHealth(h); setAuth(a);
      if(a.authenticated){
        const result=await liveApi<Jobs>("jobs?limit=20");
        setJobs(result.jobs);
      } else setJobs([]);
    }catch(cause){setError(cause instanceof Error?cause.message:String(cause));}
  }
  useEffect(()=>{void load();},[]);
  useEffect(()=>{if(!active||!["queued","running","cancelling"].includes(active.status))return;const timer=window.setInterval(async()=>{try{const res=await liveApi<{ok:true;job:ControlJob}>(`jobs/${active.id}`);setActive(res.job);if(!["queued","running","cancelling"].includes(res.job.status))void load();}catch{}},2000);return()=>window.clearInterval(timer);},[active?.id,active?.status]);

  async function login(event:FormEvent){event.preventDefault();setBusy("login");setError("");try{await liveApi<Auth>("auth/login",{method:"POST",body:JSON.stringify({token})});setToken("");await load();}catch(cause){setError(cause instanceof Error?cause.message:String(cause));}finally{setBusy("");}}
  async function logout(){setBusy("logout");try{await liveApi<Auth>("auth/logout",{method:"POST",body:"{}"});setActive(null);await load();}finally{setBusy("");}}
  async function run(operation:(typeof OPERATIONS)[number]){
    if(operation.dangerous&&!window.confirm(`Run ${operation.label}? This action can write to the production database.`))return;
    setBusy(operation.kind);setError("");
    try{
      const payload:Record<string,unknown>={kind:operation.kind,sites:"all"};
      if("existing" in operation&&operation.existing){payload.allow_existing=true;payload.reset_state=true;}
      const response=await liveApi<{ok:true;job:ControlJob}>("operations",{method:"POST",body:JSON.stringify(payload)});
      setActive(response.job);
    }catch(cause){setError(cause instanceof Error?cause.message:String(cause));}finally{setBusy("");}
  }
  async function cancel(){if(!active)return;const response=await liveApi<{ok:true;job:ControlJob}>(`jobs/${active.id}/cancel`,{method:"POST",body:"{}"});setActive(response.job);}

  return <AppShell footer><div className="page-container admin-page">
    <Breadcrumbs items={[{label:"Administration"},{label:"Operations"}]} />
    <PageHeading eyebrow="Governed execution" title="Production operations" description="Run only the repository's allowlisted scraper/ETL entry points. Arbitrary SQL and arbitrary shell execution are intentionally not exposed to the browser." actions={<button className="button button-secondary" type="button" onClick={()=>void load()}><Icon name="refresh" />Refresh</button>} />
    {error&&<div className="field-error">{error}</div>}{health?.security_warnings?.map((warning)=><div className="field-error" key={warning}>{warning}</div>)}{health?.session_cookie_secure && typeof window !== "undefined" && window.location.protocol === "http:" && <div className="field-error"><strong>Local operator login warning:</strong> MOBILE_ANALYTICS_SECURE_COOKIES=1 will not persist a session over local HTTP. Set it to 0 for http://127.0.0.1 development and back to 1 only behind HTTPS.</div>}{health?.repo_root_warning&&<div className="field-error"><strong>Repository root:</strong> {health.repo_root_warning}</div>}
    {!auth?.authenticated&&<section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Administrator authentication</span><h2>Unlock write operations</h2><p>{auth?.configured?"Enter the value of MOBILE_ANALYTICS_ADMIN_TOKEN. Any long random secret is valid; the backend exchanges the matching value for an HttpOnly SameSite session cookie.":"MOBILE_ANALYTICS_ADMIN_TOKEN is not configured on the Control API."}</p></div></div><form className="inline-form" onSubmit={login}><input type="password" autoComplete="current-password" value={token} onChange={event=>setToken(event.target.value)} placeholder="Operations token" disabled={!auth?.configured||busy==="login"}/><button className="button button-primary" disabled={!auth?.configured||!token||busy==="login"}>{busy==="login"?"Authenticating…":"Authenticate"}</button></form></section>}
    <div className="admin-grid">
      <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Control API</span><h2>Runtime readiness</h2><p>{health?.repo_root||"Repository details are shown after authentication."}</p></div><StatusBadge status={health?.database.reachable?"Database ready":"Database unavailable"} /></div>
        <div className="readiness-list"><div><span>Supabase configured</span><strong>{health?.database.configured?"Yes":"No"}</strong></div><div><span>Supabase reachable</span><strong>{health?.database.reachable?"Yes":"No"}</strong></div><div><span>Operations authentication</span><strong>{auth?.authenticated?"Authenticated":auth?.configured?"Token required":"Not configured"}</strong></div></div>
        {health?.database.error&&<div className="field-error">{health.database.error}</div>}{auth?.authenticated&&<button className="button button-secondary" type="button" onClick={()=>void logout()} disabled={busy==="logout"}>Log out</button>}
      </section>
      <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Script inventory</span><h2>Repository entry points</h2><p>Missing scripts disable the corresponding operation instead of simulating it.</p></div></div><div className="schema-tree">{health&&Object.entries(health.scripts).map(([name,item])=><div className="schema-table" key={name}><span><Icon name={item.exists?"check":"alert"}/><strong>{name}</strong></span><small>{item.path||"path hidden until authenticated"}</small><StatusBadge status={item.exists?"Ready":"Missing"}/></div>)}</div></section>
    </div>
    <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">ETL and database</span><h2>Allowlisted production actions</h2><p>The two sync actions use the loader's idempotent deterministic-ID replay mode for this already-populated project.</p></div></div><div className="operation-card-grid">{OPERATIONS.map((operation)=><article className="operation-card" key={operation.kind}><span className={operation.dangerous?"operation-icon danger":"operation-icon"}><Icon name={operation.dangerous?"alert":"terminal"}/></span><div><strong>{operation.label}</strong><p>{operation.description}</p></div><button className={`button ${operation.dangerous?"button-danger":"button-primary"}`} type="button" disabled={!!busy||!auth?.authenticated} onClick={()=>void run(operation)}>{busy===operation.kind?"Starting…":"Run"}</button></article>)}</div>{!auth?.authenticated&&<div className="field-error">Authenticate above before starting any repository process.</div>}</section>
    {active&&<section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Persisted execution</span><h2>{active.id}</h2><p>{active.label}</p></div><StatusBadge status={active.status}/></div><div className="job-progress-summary"><span>Step <b>{active.current_step}</b> / {active.total_steps}</span><span>Started <b>{active.started_at||"queued"}</b></span></div><pre className="job-log">{active.log_tail||"Waiting for process output…"}</pre>{["queued","running"].includes(active.status)&&<button className="button button-danger" type="button" onClick={()=>void cancel()}><Icon name="square"/>Cancel job</button>}{active.error&&<div className="field-error">{active.error}</div>}</section>}
    <section className="panel"><div className="panel-heading"><div><span className="panel-kicker">Local history</span><h2>Recent control-plane jobs</h2><p>Metadata persists in filestorage/control_plane_jobs and is visible only after operator authentication.</p></div></div><div className="saved-query-list">{jobs.length?jobs.map(job=><button className="saved-query" key={job.id} onClick={async()=>{try{const res=await liveApi<{ok:true;job:ControlJob}>(`jobs/${job.id}`);setActive(res.job);}catch{setActive(job);}}}><span><Icon name="history"/><strong>{job.id}</strong><small>{job.label} · {job.status}</small></span><Icon name="chevron-right"/></button>):<div className="table-empty">{auth?.authenticated?"No control-plane jobs yet.":"Authenticate to view job history."}</div>}</div></section>
  </div></AppShell>;
}
