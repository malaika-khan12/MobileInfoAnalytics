from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_repo_root() -> Path:
    configured = os.getenv("MOBILE_ANALYTICS_REPO_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    here = Path(__file__).resolve()
    # backend/control_plane.py -> repository root
    candidate = here.parent.parent
    if (candidate / "filestorage").exists() or (candidate / "frontend").exists():
        return candidate
    return Path.cwd().resolve()


REPO_ROOT = resolve_repo_root()
_read_env_file(REPO_ROOT / ".env")


class ControlPlaneError(RuntimeError):
    pass


class SupabaseError(ControlPlaneError):
    def __init__(self, message: str, *, status: int | None = None, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


class SupabaseREST:
    """Tiny dependency-free PostgREST client for the finalized Supabase schemas."""

    def __init__(self) -> None:
        self.base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.secret_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        self.publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        self.timeout = int(os.getenv("MOBILE_ANALYTICS_DB_TIMEOUT", "20"))

    @property
    def configured(self) -> bool:
        return bool(self.base_url and (self.secret_key or self.publishable_key))

    def _key(self, privileged: bool) -> str:
        # All browser traffic reaches Supabase through this server-side control plane.
        # Prefer the server secret for consistent security_invoker-view access; a
        # publishable key remains a read-only fallback for deliberately public setups.
        key = self.secret_key or (None if privileged else self.publishable_key)
        if not self.base_url:
            raise SupabaseError("SUPABASE_URL is not configured")
        if not key:
            needed = "SUPABASE_SECRET_KEY/SUPABASE_KEY" if privileged else "SUPABASE_PUBLISHABLE_KEY or server key"
            raise SupabaseError(f"{needed} is not configured")
        return key

    @staticmethod
    def _headers(key: str, schema: str, *, count: bool = False) -> dict[str, str]:
        headers = {
            "apikey": key,
            "Accept": "application/json",
            "Accept-Profile": schema,
            "User-Agent": "MobileInfoAnalytics-ControlPlane/1.0",
        }
        # Legacy anon/service_role keys are JWTs. New sb_publishable/sb_secret keys
        # are opaque and belong in apikey, not Authorization.
        if key.count(".") == 2 and not key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {key}"
        if count:
            headers["Prefer"] = "count=exact"
        return headers

    def get(
        self,
        schema: str,
        resource: str,
        *,
        params: dict[str, str | int] | None = None,
        privileged: bool = False,
        count: bool = False,
        range_start: int | None = None,
        range_end: int | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        key = self._key(privileged)
        query = urlencode(params or {}, safe="(),.*:-_")
        url = f"{self.base_url}/rest/v1/{resource}"
        if query:
            url += "?" + query
        headers = self._headers(key, schema, count=count)
        if range_start is not None:
            headers["Range-Unit"] = "items"
            headers["Range"] = f"{range_start}-{range_end if range_end is not None else range_start}"
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body) if body else []
                if not isinstance(data, list):
                    raise SupabaseError("Unexpected Supabase response shape", status=response.status, detail=data)
                total = None
                content_range = response.headers.get("Content-Range")
                if content_range and "/" in content_range:
                    tail = content_range.rsplit("/", 1)[1]
                    if tail.isdigit():
                        total = int(tail)
                return data, total
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
            except json.JSONDecodeError:
                detail = raw
            raise SupabaseError(f"Supabase REST request failed with HTTP {exc.code}", status=exc.code, detail=detail) from exc
        except URLError as exc:
            raise SupabaseError(f"Could not reach Supabase: {exc.reason}") from exc

    def count(self, schema: str, resource: str, *, privileged: bool = False, params: dict[str, str] | None = None) -> int:
        _, total = self.get(schema, resource, params={"select": "*", **(params or {})}, privileged=privileged, count=True, range_start=0, range_end=0)
        return total or 0


VIEW_REGISTRY: dict[str, dict[str, Any]] = {
    "products": {
        "schema": "analytics",
        "resource": "v_canonical_products",
        "id": "product_id",
        "select": "product_id,company_name,mobile_name,product_slug,created_by_source,release_year,release_month,release_day,status_text,specs_source,supports_5g,screen_technology,refresh_rate_hz,pixel_density_ppi,operating_system,chipset_name,storage_ram_variants,capacity_mah,has_wireless_charging",
        "search": ("company_name", "mobile_name", "chipset_name", "operating_system"),
        "order": "product_id.desc",
    },
    "listings": {
        "schema": "analytics",
        "resource": "v_market_listings_full",
        "id": "listing_id",
        "select": "listing_id,product_id,company_name,canonical_product_name,instance_number,source_domain,source_url,listing_title,release_year,release_month,scraped_at,prices,screen_technology,refresh_rate_hz,resolution,chipset_name,operating_system,storage_ram_variants,weight_grams,capacity_mah",
        "search": ("company_name", "canonical_product_name", "listing_title", "source_domain"),
        "order": "scraped_at.desc",
    },
    "prices": {
        "schema": "analytics",
        "resource": "v_price_comparison",
        "id": "product_id",
        "select": "product_id,company_name,mobile_name,currency_code,sources_count,total_listings,min_price,avg_price,max_price,price_spread,listings_detail",
        "search": ("company_name", "mobile_name", "currency_code"),
        "order": "price_spread.desc.nullslast",
    },
    "discrepancies": {
        "schema": "analytics",
        "resource": "v_spec_discrepancies",
        "id": "product_id",
        "select": "product_id,company_name,mobile_name,source_domain,listing_title,canonical_battery_mah,listing_battery_mah,battery_discrepancy,canonical_screen,listing_screen,screen_discrepancy,canonical_refresh_hz,listing_refresh_hz,refresh_discrepancy,canonical_memory,listing_memory",
        "search": ("company_name", "mobile_name", "source_domain", "listing_title"),
        "order": "product_id.desc",
    },
    "site_summary": {
        "schema": "analytics",
        "resource": "v_site_summary",
        "id": "source_domain",
        "select": "source_domain,distinct_products_covered,total_listings,avg_data_completeness_pct,first_scraped_at,last_scraped_at",
        "search": ("source_domain",),
        "order": "total_listings.desc",
    },
    "scrape_runs": {
        "schema": "metadata",
        "resource": "scrape_runs",
        "id": "run_id",
        "select": "run_id,source_domain,started_at,finished_at,records_processed,records_succeeded,records_failed,run_status",
        "search": ("source_domain", "run_status"),
        "order": "started_at.desc",
        "privileged": True,
    },
    "quality": {
        "schema": "metadata",
        "resource": "data_quality",
        "id": "score_id",
        "select": "score_id,product_id,listing_id,source_domain,completeness_pct,fields_populated,fields_total,scored_at",
        "search": ("source_domain",),
        "order": "scored_at.desc",
        "privileged": True,
    },
    "rejects": {
        "schema": "metadata",
        "resource": "etl_rejects",
        "id": "reject_id",
        "select": "reject_id,scrape_run_id,source_domain,source_url,source_file,reject_reason,reject_detail,rejected_at,resolved_at,resolution_detail",
        "search": ("source_domain", "source_file", "reject_reason"),
        "order": "rejected_at.desc",
        "privileged": True,
    },
}


def _clean_search(value: str) -> str:
    value = re.sub(r"[(),]", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()[:120]


def query_view(client: SupabaseREST, view: str, *, limit: int = 25, offset: int = 0, search: str = "", filters: dict[str, str] | None = None) -> dict[str, Any]:
    if view not in VIEW_REGISTRY:
        raise ControlPlaneError(f"Unknown view {view!r}")
    spec = VIEW_REGISTRY[view]
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    params: dict[str, str | int] = {"select": spec["select"], "order": spec["order"]}
    q = _clean_search(search)
    if q:
        params["or"] = "(" + ",".join(f"{column}.ilike.*{q}*" for column in spec["search"]) + ")"
    allowed_filters = {
        "source_domain", "company_name", "release_year", "currency_code", "run_status",
        "supports_5g", "screen_technology", "operating_system", "specs_source",
    }
    for key, value in (filters or {}).items():
        if key in allowed_filters and value not in (None, "", "all"):
            params[key] = f"eq.{str(value)[:80]}"
    rows, total = client.get(
        spec["schema"],
        spec["resource"],
        params=params,
        privileged=bool(spec.get("privileged")),
        count=True,
        range_start=offset,
        range_end=offset + limit - 1,
    )
    return {"view": view, "rows": rows, "total": total if total is not None else len(rows), "limit": limit, "offset": offset}


def _average(values: Iterable[float]) -> float | None:
    values = list(values)
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def dashboard_payload(client: SupabaseREST) -> dict[str, Any]:
    sites, _ = client.get("analytics", "v_site_summary", params={"select": VIEW_REGISTRY["site_summary"]["select"], "order": "total_listings.desc"})
    products_count = client.count("catalog", "products")
    listings_count = client.count("listings", "market_listings")
    companies_count = client.count("catalog", "companies")
    price_count = client.count("listings", "listing_prices")
    quality_rows, _ = client.get("metadata", "data_quality", params={"select": "completeness_pct", "order": "scored_at.desc"}, privileged=True, range_start=0, range_end=999)
    avg_quality = _average(float(row["completeness_pct"]) for row in quality_rows if row.get("completeness_pct") is not None)
    recent_products, _ = client.get("analytics", "v_canonical_products", params={"select": VIEW_REGISTRY["products"]["select"], "order": "product_id.desc"}, range_start=0, range_end=9)
    price_rows, _ = client.get("analytics", "v_price_comparison", params={"select": "product_id,company_name,mobile_name,currency_code,min_price,avg_price,max_price,price_spread,sources_count,total_listings", "order": "price_spread.desc.nullslast"}, range_start=0, range_end=9)
    run_rows, _ = client.get("metadata", "scrape_runs", params={"select": VIEW_REGISTRY["scrape_runs"]["select"], "order": "started_at.desc"}, privileged=True, range_start=0, range_end=9)
    return {
        "generated_at": utc_now(),
        "metrics": {
            "companies": companies_count,
            "products": products_count,
            "listings": listings_count,
            "price_entries": price_count,
            "avg_completeness_pct": avg_quality,
        },
        "sources": sites,
        "recent_products": recent_products,
        "price_spreads": price_rows,
        "recent_runs": run_rows,
    }


SCRAPER_SCRIPTS = {
    "mymobile": "backend/navigation_to_page/mymobile.pk.py",
    "daraz": "backend/navigation_to_page/www.daraz.pk.py",
    "gsmarena": "backend/navigation_to_page/www.gsmarena.com.py",
    "mega": "backend/navigation_to_page/www.mega.pk.py",
    "whatamobile": "backend/navigation_to_page/www.whatamobile.com.pk.py",
    "whatmobile": "backend/navigation_to_page/www.whatmobile.com.pk.py",
}
SOURCE_DOMAINS = {
    "mymobile": "mymobile.pk",
    "daraz": "daraz.pk",
    "gsmarena": "gsmarena.com",
    "mega": "mega.pk",
    "whatamobile": "whatamobile.com.pk",
    "whatmobile": "whatmobile.com.pk",
}


VALID_SITES = set(SOURCE_DOMAINS.values())


def _validated_site_csv(value: Any) -> tuple[str, list[str]]:
    if isinstance(value, list):
        requested = [str(item).strip().lower() for item in value if str(item).strip()]
    else:
        raw = str(value or "all").strip().lower()
        if raw == "all":
            return "all", []
        requested = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = sorted(set(requested) - VALID_SITES)
    if invalid:
        raise ControlPlaneError("Unsupported source site(s): " + ", ".join(invalid))
    unique = list(dict.fromkeys(requested))
    return ",".join(unique) if unique else "all", unique


def _validated_source_url(source: str, raw: Any) -> str:
    url = str(raw or "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parsed.scheme not in {"http", "https"} or host != SOURCE_DOMAINS[source]:
        raise ControlPlaneError(f"URL must be an HTTP(S) URL on {SOURCE_DOMAINS[source]}")
    return url


@dataclass
class Job:
    id: str
    kind: str
    label: str
    command: list[str] | None = None
    commands: list[list[str]] | None = None
    status: str = "queued"
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    current_step: int = 0
    total_steps: int = 1
    log_path: str = ""
    error: str | None = None


class JobManager:
    def __init__(self, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = repo_root
        self.jobs_dir = repo_root / "filestorage" / "control_plane_jobs"
        self._storage_error: str | None = None
        try:
            self.jobs_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._storage_error = str(exc)
        self._jobs: dict[str, Job] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()
        self._load_existing()

    def _metadata_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _save(self, job: Job) -> None:
        if self._storage_error:
            raise ControlPlaneError(f"Control-plane job storage is not writable: {self._storage_error}")
        tmp = self._metadata_path(job.id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(job), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self._metadata_path(job.id))

    def _load_existing(self) -> None:
        if self._storage_error or not self.jobs_dir.is_dir():
            return
        for path in sorted(self.jobs_dir.glob("*.json"), reverse=True):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                job = Job(**raw)
                if job.status in {"queued", "running", "cancelling"}:
                    job.status = "interrupted"
                    job.finished_at = utc_now()
                    job.error = "Control-plane process restarted before this job finished."
                    self._save(job)
                self._jobs[job.id] = job
            except Exception:
                continue

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)[: max(1, min(limit, 100))]
            return [self._public(job) for job in jobs]

    def get(self, job_id: str, *, include_log: bool = True) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ControlPlaneError("Job not found")
            return self._public(job, include_log=include_log)

    def _public(self, job: Job, *, include_log: bool = False) -> dict[str, Any]:
        data = asdict(job)
        data.pop("command", None)
        data.pop("commands", None)
        data.pop("log_path", None)
        if include_log:
            path = Path(job.log_path)
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                data["log_tail"] = text[-24000:]
            else:
                data["log_tail"] = ""
        return data

    def submit(self, *, kind: str, label: str, command: list[str] | None = None, commands: list[list[str]] | None = None) -> dict[str, Any]:
        if not command and not commands:
            raise ControlPlaneError("No command supplied")
        active_states = {"queued", "running", "cancelling"}
        exclusive_kinds = {"organise", "convert", "upload-dry-run", "upload-preflight", "upload-resume", "upload", "full-pipeline"}
        with self._lock:
            active = [job for job in self._jobs.values() if job.status in active_states]
            if kind in exclusive_kinds and active:
                raise ControlPlaneError("An active control-plane job must finish or be cancelled before this ETL/database operation starts.")
            if kind == "scrape" and any(job.kind in exclusive_kinds for job in active):
                raise ControlPlaneError("A scraper cannot start while an ETL/database operation is active.")
        job_id = "JOB-" + uuid.uuid4().hex[:12].upper()
        log_path = self.jobs_dir / f"{job_id}.log"
        total_steps = len(commands) if commands else 1
        job = Job(id=job_id, kind=kind, label=label, command=command, commands=commands, total_steps=total_steps, log_path=str(log_path))
        with self._lock:
            self._jobs[job.id] = job
            self._save(job)
        threading.Thread(target=self._run, args=(job.id,), daemon=True, name=f"control-{job.id}").start()
        return self._public(job)

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at = utc_now()
            self._save(job)
        commands = job.commands or ([job.command] if job.command else [])
        try:
            with Path(job.log_path).open("a", encoding="utf-8", buffering=1) as log:
                for index, command in enumerate(commands, start=1):
                    with self._lock:
                        if job.status == "cancelling":
                            job.status = "cancelled"
                            job.finished_at = utc_now()
                            self._save(job)
                            return
                        job.current_step = index
                        self._save(job)
                    log.write(f"\n[{utc_now()}] STEP {index}/{len(commands)}\n$ {' '.join(command)}\n")
                    env = os.environ.copy()
                    env["PYTHONUNBUFFERED"] = "1"
                    kwargs: dict[str, Any] = {
                        "cwd": str(self.repo_root),
                        "stdout": log,
                        "stderr": subprocess.STDOUT,
                        "text": True,
                        "env": env,
                    }
                    if os.name != "nt":
                        kwargs["start_new_session"] = True
                    else:
                        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    kwargs["stdin"] = subprocess.DEVNULL
                    process = subprocess.Popen(command, **kwargs)
                    with self._lock:
                        self._processes[job.id] = process
                    rc = process.wait()
                    with self._lock:
                        self._processes.pop(job.id, None)
                    if rc != 0:
                        raise ControlPlaneError(f"Step {index} exited with code {rc}")
                with self._lock:
                    job.return_code = 0
                    job.status = "completed"
                    job.finished_at = utc_now()
                    self._save(job)
        except Exception as exc:
            with self._lock:
                if job.status == "cancelling":
                    job.status = "cancelled"
                else:
                    job.status = "failed"
                    job.error = str(exc)
                job.finished_at = utc_now()
                self._save(job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ControlPlaneError("Job not found")
            if job.status not in {"queued", "running"}:
                return self._public(job, include_log=True)
            job.status = "cancelling"
            self._save(job)
            process = self._processes.get(job_id)
        if process and process.poll() is None:
            try:
                if os.name == "nt":
                    # The Python navigator may own Chromium children. taskkill /T
                    # terminates the process tree without invoking a shell.
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    os.killpg(process.pid, signal.SIGTERM)
            except Exception:
                process.terminate()
        return self.get(job_id, include_log=True)


JOB_MANAGER = JobManager()


def _python() -> str:
    return sys.executable or "python"


def _script(path: str) -> str:
    target = REPO_ROOT / path
    if not target.is_file():
        raise ControlPlaneError(f"Required script does not exist: {path}")
    return str(target)


def build_operation(payload: dict[str, Any]) -> tuple[str, str, list[str] | None, list[list[str]] | None]:
    kind = str(payload.get("kind") or "").strip().lower()
    if kind == "scrape":
        source = str(payload.get("source") or "").strip().lower()
        if source not in SCRAPER_SCRIPTS:
            raise ControlPlaneError("Unknown scraper source")
        mode = str(payload.get("mode") or "range").lower()
        base = [_python(), _script(SCRAPER_SCRIPTS[source])]
        force = bool(payload.get("force"))
        headed = bool(payload.get("headed"))
        if force:
            base.append("--force")
        if headed:
            base.append("--headed")
        retries = max(0, min(int(payload.get("retries", 2)), 5))
        base += ["--retries", str(retries)]
        if source == "gsmarena":
            delay_min = max(10.0, float(payload.get("delay_min", 12.0)))
            delay_max = max(delay_min, float(payload.get("delay_max", 14.0)))
        else:
            delay_min = max(0.0, float(payload.get("delay_min", 2.0)))
            delay_max = max(delay_min, float(payload.get("delay_max", 5.0)))
        base += ["--delay-min", str(delay_min), "--delay-max", str(delay_max)]
        if mode == "single":
            url = _validated_source_url(source, payload.get("url"))
            # These navigators discover products from catalogue/category pages rather
            # than accepting a product URL as their positional argument.
            if source in {"daraz", "whatmobile"}:
                raise ControlPlaneError(f"{SOURCE_DOMAINS[source]} single-product mode is not implemented by the current navigator; use range/full catalogue mode.")
            return kind, f"Scrape {SOURCE_DOMAINS[source]} single URL", base[:2] + [url] + base[2:], None
        if mode == "multiple":
            urls = payload.get("urls")
            if isinstance(urls, str):
                urls = [line.strip() for line in urls.splitlines() if line.strip()]
            if not isinstance(urls, list) or not (2 <= len(urls) <= 100):
                raise ControlPlaneError("Multiple mode requires 2-100 URLs")
            if source in {"daraz", "whatmobile"}:
                raise ControlPlaneError(f"{SOURCE_DOMAINS[source]} multiple-product mode is not implemented by the current navigator; use range/full catalogue mode.")
            commands = []
            for raw in urls:
                url = _validated_source_url(source, raw)
                commands.append(base[:2] + [url] + base[2:])
            return kind, f"Scrape {SOURCE_DOMAINS[source]} URL batch", None, commands
        if mode == "range":
            minimum = max(1, int(payload.get("minimum", 1)))
            maximum = int(payload.get("maximum", minimum))
            if maximum < minimum:
                raise ControlPlaneError("maximum must be greater than or equal to minimum")
            command = base + ["--min", str(minimum), "--max", str(maximum)]
            return kind, f"Scrape {SOURCE_DOMAINS[source]} positions {minimum}-{maximum}", command, None
        if mode == "full":
            command = base + ["--min", "1"]
            return kind, f"Scrape {SOURCE_DOMAINS[source]} full resumable catalogue", command, None
        raise ControlPlaneError("Unsupported scrape mode")

    if kind == "organise":
        sites, _selected_sites = _validated_site_csv(payload.get("sites", "all"))
        command = [_python(), _script("filestorage/organise_with_llm.py"), "--root", str(REPO_ROOT), "--sites", sites]
        if payload.get("fresh"):
            command.append("--fresh")
        limit = payload.get("limit")
        if limit not in (None, ""):
            command += ["--limit", str(max(1, int(limit)))]
        return kind, f"Organise mobile JSON ({sites})", command, None

    if kind == "convert":
        command = [_python(), _script("filestorage/jsonToCsv.py")]
        raw_sites = payload.get("sites") or []
        if raw_sites:
            _site_csv, sites = _validated_site_csv(raw_sites)
        else:
            sites = []
        for site in sites:
            command += ["--site", site]
        if payload.get("strict"):
            command.append("--strict")
        return kind, "Convert organised JSON to Supabase CSV tables", command, None

    if kind == "upload-dry-run":
        return kind, "Validate all CSV tables", [_python(), _script("filestorage/csvToDataBase.py"), "--dry-run"], None
    if kind == "upload-preflight":
        command = [_python(), _script("filestorage/csvToDataBase.py"), "--preflight-only"]
        if payload.get("allow_existing"):
            command.append("--allow-existing")
        if payload.get("reset_state"):
            command.append("--reset-state")
        return kind, "Supabase upload preflight", command, None
    if kind == "upload-resume":
        return kind, "Resume current Supabase upload state", [_python(), _script("filestorage/csvToDataBase.py")], None

    if kind == "upload":
        command = [_python(), _script("filestorage/csvToDataBase.py")]
        if payload.get("allow_existing"):
            command.append("--allow-existing")
        if payload.get("continue_on_error"):
            command.append("--continue-on-error")
        if payload.get("reset_state"):
            command.append("--reset-state")
        return kind, "Upload CSV hierarchy to Supabase", command, None

    if kind == "full-pipeline":
        site_csv, selected_sites = _validated_site_csv(payload.get("sites", "all"))
        preflight = [_python(), _script("filestorage/csvToDataBase.py"), "--preflight-only"]
        # jsonToCsv regenerates the contract. Resetting the local loader state is
        # required when that fingerprint changes; --allow-existing is explicit
        # because the loader intentionally refuses a populated target otherwise.
        if payload.get("reset_state"):
            preflight.append("--reset-state")
        if payload.get("allow_existing"):
            preflight.append("--allow-existing")
        commands = [
            [_python(), _script("filestorage/organise_with_llm.py"), "--root", str(REPO_ROOT), "--sites", site_csv],
            [_python(), _script("filestorage/jsonToCsv.py")] + sum((["--site", str(site)] for site in selected_sites), []),
            [_python(), _script("filestorage/csvToDataBase.py"), "--dry-run"],
            preflight,
            [_python(), _script("filestorage/csvToDataBase.py")],
        ]
        return kind, f"Full ETL pipeline ({site_csv})", None, commands

    raise ControlPlaneError("Unknown operation kind")


def pipeline_status(client: SupabaseREST | None = None) -> dict[str, Any]:
    scripts = {
        name: {"path": path, "exists": (REPO_ROOT / path).is_file()}
        for name, path in {
            **{f"scraper:{key}": value for key, value in SCRAPER_SCRIPTS.items()},
            "organise": "filestorage/organise_with_llm.py",
            "convert": "filestorage/jsonToCsv.py",
            "upload": "filestorage/csvToDataBase.py",
        }.items()
    }
    db: dict[str, Any] = {"configured": bool(client and client.configured), "reachable": False}
    if client and client.configured:
        try:
            rows, _ = client.get("analytics", "v_site_summary", params={"select": "source_domain,total_listings", "order": "total_listings.desc"}, range_start=0, range_end=5)
            db.update({"reachable": True, "site_rows": len(rows)})
        except Exception as exc:
            db["error"] = str(exc)
            if isinstance(exc, SupabaseError):
                db["detail"] = exc.detail
    return {"repo_root": str(REPO_ROOT), "database": db, "scripts": scripts, "jobs": JOB_MANAGER.list(10)}
