"""Flask entry point for the Mobile Analytics frontend."""
from pathlib import Path
from flask import Flask, render_template, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder="templates", static_folder="static")


@app.get("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(BASE_DIR / "assets", filename)


@app.get("/")
@app.get("/dashboard")
@app.get("/scrapers")
@app.get("/scrapers/<source>")
@app.get("/admin")
@app.get("/database")
@app.get("/realtime")
def index(source=None):
    """Serve the shared application shell; vanilla JS resolves the route."""
    return render_template("index.html")


@app.errorhandler(404)
def not_found(_error):
    return render_template("index.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
