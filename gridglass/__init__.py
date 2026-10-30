"""Gridglass — simple spreadsheet tools, like ilovepdf for spreadsheets."""
from __future__ import annotations

import logging
import mimetypes
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config

__version__ = "1.0.0"
log = logging.getLogger("gridglass")
mimetypes.add_type("application/manifest+json", ".webmanifest")

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "font-src 'self'",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def create_app(config: type[Config] = Config, **overrides: Any) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config)
    app.config.update(overrides)
    if app.config["TRUST_PROXY"]:
        n = app.config["TRUST_PROXY"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)
    if not app.debug and not app.testing:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from .limits import limiter

    limiter.init_app(app)

    from .storage import Store

    store = Store(Path(app.config["DATA_DIR"]), app.config["FILE_RETENTION_MINUTES"], app.config["MAX_CONTENT_LENGTH"])
    app.extensions["gridglass_store"] = store

    from .api import bp
    from .engine.steps import Pivot

    Pivot.max_columns = app.config["MAX_PIVOT_COLUMNS"]

    app.register_blueprint(bp)

    @app.get("/healthz")
    def healthz():
        import polars as pl

        from .engine import OPS

        return jsonify(status="ok", version=__version__, polars=pl.__version__, tools=len(OPS))

    @app.get("/")
    def index():
        resp = send_from_directory(app.static_folder, "index.html", max_age=0)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/sw.js")
    def service_worker():  # served from the root so it can control the whole app
        resp = send_from_directory(app.static_folder, "sw.js", max_age=0)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        if not request.path.startswith("/api/"):
            return exc
        messages = {
            413: f"This file is larger than the {app.config['MAX_UPLOAD_MB']} MB limit.",
            429: "You're going a bit fast — please wait a minute and try again.",
        }
        code = exc.name.lower().replace(" ", "_")
        return jsonify(error={"code": code, "message": messages.get(exc.code, exc.description)}), exc.code

    @app.errorhandler(Exception)
    def unexpected(exc: Exception):
        log.exception("Unhandled error on %s", request.path)
        return jsonify(error={"code": "server_error", "message": "Something went wrong on our side. Please try again."}), 500

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        if request.is_secure:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"  # user data is never cached
        else:
            resp.headers.setdefault("Content-Security-Policy", CSP)
        return resp

    @app.cli.command("purge")
    def purge_command():
        """Delete expired uploads (run from cron if the background cleaner is off)."""
        print(f"Removed {store.purge_expired()} expired uploads.")

    interval = app.config.get("CLEANUP_INTERVAL_SECONDS", 0)
    if interval and not app.testing:
        _start_cleaner(store, interval)

    return app


def _start_cleaner(store, interval: int) -> None:
    def loop():
        stop = threading.Event()
        while not stop.wait(interval):
            try:
                removed = store.purge_expired()
                if removed:
                    log.info("Purged %d expired uploads", removed)
            except Exception:  # never let cleanup kill the worker
                log.exception("Cleanup failed")

    threading.Thread(target=loop, name="gridglass-cleaner", daemon=True).start()
