"""Production Flask frontend and API gateway for MobileInfoAnalytics."""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from flask import Flask, render_template, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.control_api import create_control_blueprint  # noqa: E402

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY") or os.getenv("MOBILE_ANALYTICS_SESSION_SECRET") or secrets.token_hex(32),
    SESSION_COOKIE_NAME="mobile_analytics_ops",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=os.getenv("MOBILE_ANALYTICS_SECURE_COOKIES", "0") == "1",
    MAX_CONTENT_LENGTH=256 * 1024,
)
app.register_blueprint(create_control_blueprint("frontend_control_api"))


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
    )
    return response


@app.get("/assets/<path:filename>")
def assets(filename: str):
    return send_from_directory(BASE_DIR / "assets", filename)


@app.get("/")
@app.get("/dashboard")
@app.get("/scrapers")
@app.get("/scrapers/<source>")
@app.get("/admin")
@app.get("/database")
@app.get("/realtime")
def index(source: str | None = None):
    return render_template("index.html")


@app.errorhandler(404)
def not_found(_error):
    return render_template("index.html"), 404


if __name__ == "__main__":
    app.run(host=os.getenv("FLASK_HOST", "127.0.0.1"), port=int(os.getenv("FLASK_PORT", "5000")), debug=False)
