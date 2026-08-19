from __future__ import annotations

import hmac
import os
import secrets
from typing import Any

from flask import Blueprint, Flask, current_app, jsonify, request, session

from .control_plane import (
    ControlPlaneError,
    JOB_MANAGER,
    SupabaseError,
    SupabaseREST,
    VIEW_REGISTRY,
    build_operation,
    dashboard_payload,
    pipeline_status,
    query_view,
)


def _json_error(message: str, status: int = 400, *, detail: Any = None):
    payload: dict[str, Any] = {"ok": False, "error": message}
    if detail is not None:
        payload["detail"] = detail
    return jsonify(payload), status


def _configured_admin_token() -> str:
    return os.getenv("MOBILE_ANALYTICS_ADMIN_TOKEN", "")


def _authorized() -> bool:
    configured = _configured_admin_token()
    if not configured:
        return False
    bearer = request.headers.get("Authorization", "")
    if bearer.startswith("Bearer ") and hmac.compare_digest(bearer[7:], configured):
        return True
    return bool(session.get("mobile_analytics_admin"))


def create_control_blueprint(name: str = "control_api") -> Blueprint:
    bp = Blueprint(name, __name__)
    db = SupabaseREST()

    @bp.after_request
    def no_store(response):
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @bp.get("/api/health")
    def health():
        status = pipeline_status(db)
        if not _authorized():
            status.pop("repo_root", None)
            status.pop("configured_repo_root", None)
            status.pop("jobs", None)
            status["scripts"] = {name: {"exists": item["exists"]} for name, item in status["scripts"].items()}
            database = status.get("database")
            if isinstance(database, dict):
                database.pop("detail", None)
                if database.get("error"):
                    database["error"] = "Database health check failed."
        status["session_cookie_secure"] = bool(current_app.config.get("SESSION_COOKIE_SECURE"))
        warnings: list[str] = []
        admin_token = _configured_admin_token()
        if admin_token and len(admin_token) < 32:
            warnings.append("MOBILE_ANALYTICS_ADMIN_TOKEN is short; use a generated random value of at least 32 characters.")
        session_secret = os.getenv("FLASK_SECRET_KEY") or os.getenv("MOBILE_ANALYTICS_SESSION_SECRET") or ""
        if session_secret and len(session_secret) < 32:
            warnings.append("FLASK_SECRET_KEY/MOBILE_ANALYTICS_SESSION_SECRET is short; use a generated random value of at least 32 characters.")
        if status["session_cookie_secure"] and not request.is_secure and request.host.split(":", 1)[0] in {"127.0.0.1", "localhost"}:
            warnings.append("Secure cookies are enabled on local HTTP; operator login will not persist until MOBILE_ANALYTICS_SECURE_COOKIES=0 or HTTPS is used.")
        status["security_warnings"] = warnings
        return jsonify({"ok": True, **status})

    @bp.get("/api/dashboard")
    def dashboard():
        try:
            payload = dashboard_payload(db)
            # Raw operational run history is not public analytics. Keep the
            # public dashboard useful while withholding metadata.scrape_runs
            # until the operator session has been authenticated.
            if not _authorized():
                payload.pop("recent_runs", None)
            return jsonify({"ok": True, **payload})
        except SupabaseError as exc:
            return _json_error(str(exc), exc.status or 503, detail=exc.detail if _authorized() else None)

    @bp.get("/api/views")
    def views():
        return jsonify({"ok": True, "views": {key: {k: v for k, v in spec.items() if k not in {"search"}} for key, spec in VIEW_REGISTRY.items()}})

    @bp.get("/api/data/<view>")
    def data(view: str):
        try:
            if view in VIEW_REGISTRY and VIEW_REGISTRY[view].get("privileged") and not _authorized():
                return _json_error("Administrator authentication required for operational metadata.", 401)
            limit = int(request.args.get("limit", "25"))
            offset = int(request.args.get("offset", "0"))
            search = request.args.get("q", "")
            filters = {key[2:]: value for key, value in request.args.items() if key.startswith("f_")}
            return jsonify({"ok": True, **query_view(db, view, limit=limit, offset=offset, search=search, filters=filters)})
        except (ValueError, ControlPlaneError) as exc:
            return _json_error(str(exc), 400)
        except SupabaseError as exc:
            return _json_error(str(exc), exc.status or 503, detail=exc.detail if _authorized() else None)

    @bp.post("/api/auth/login")
    def login():
        configured = _configured_admin_token()
        if not configured:
            return _json_error("Operations authentication is not configured on the server.", 503)
        payload = request.get_json(silent=True) or {}
        token = str(payload.get("token") or "")
        if not hmac.compare_digest(token, configured):
            return _json_error("Invalid operations token.", 401)
        session["mobile_analytics_admin"] = True
        return jsonify({"ok": True, "authenticated": True})

    @bp.post("/api/auth/logout")
    def logout():
        session.pop("mobile_analytics_admin", None)
        return jsonify({"ok": True, "authenticated": False})

    @bp.get("/api/auth/status")
    def auth_status():
        return jsonify({"ok": True, "authenticated": _authorized(), "configured": bool(_configured_admin_token())})

    @bp.get("/api/jobs")
    def jobs():
        if not _authorized():
            return _json_error("Administrator authentication required.", 401)
        return jsonify({"ok": True, "jobs": JOB_MANAGER.list(int(request.args.get("limit", "30")))})

    @bp.get("/api/jobs/<job_id>")
    def job(job_id: str):
        if not _authorized():
            return _json_error("Administrator authentication required.", 401)
        try:
            return jsonify({"ok": True, "job": JOB_MANAGER.get(job_id)})
        except ControlPlaneError as exc:
            return _json_error(str(exc), 404)

    @bp.post("/api/jobs/<job_id>/cancel")
    def cancel_job(job_id: str):
        if not _authorized():
            return _json_error("Administrator authentication required.", 401)
        try:
            return jsonify({"ok": True, "job": JOB_MANAGER.cancel(job_id)})
        except ControlPlaneError as exc:
            return _json_error(str(exc), 404)

    @bp.post("/api/operations")
    def operation():
        if not _authorized():
            return _json_error("Administrator authentication required.", 401)
        payload = request.get_json(silent=True) or {}
        try:
            kind, label, command, commands = build_operation(payload)
            job = JOB_MANAGER.submit(kind=kind, label=label, command=command, commands=commands)
            return jsonify({"ok": True, "job": job}), 202
        except (ControlPlaneError, ValueError) as exc:
            return _json_error(str(exc), 400)

    return bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY") or os.getenv("MOBILE_ANALYTICS_SESSION_SECRET") or secrets.token_hex(32),
        SESSION_COOKIE_NAME="mobile_analytics_ops",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.getenv("MOBILE_ANALYTICS_SECURE_COOKIES", "0") == "1",
        MAX_CONTENT_LENGTH=256 * 1024,
    )
    app.register_blueprint(create_control_blueprint())

    @app.get("/")
    def service_root():
        return jsonify({
            "ok": True,
            "service": "MobileInfoAnalytics Control API",
            "message": "The control API is running. Open the TypeScript frontend separately (normally http://127.0.0.1:3000).",
            "health": "/api/health",
            "auth_status": "/api/auth/status",
        })

    return app


if __name__ == "__main__":
    from waitress import serve

    serve(
        create_app(),
        host=os.getenv("CONTROL_API_HOST", "127.0.0.1"),
        port=int(os.getenv("CONTROL_API_PORT", "5050")),
        threads=max(4, int(os.getenv("CONTROL_API_THREADS", "8"))),
    )
