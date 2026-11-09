"""Gridglass — simple spreadsheet tools, simple tools for spreadsheets."""
from __future__ import annotations

import logging
import mimetypes
import re
import threading
from pathlib import Path
from typing import Any

from urllib.parse import quote

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config

__version__ = "1.16.0"
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

    from .engine import GridglassError
    from .limits import from_config, limiter

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

    from .site import bp as site_bp, site_url

    app.register_blueprint(site_bp)
    client = app.config.get("ADSENSE_CLIENT", "")
    if client and not re.fullmatch(r"ca-pub-\d{10,20}", client):
        raise ValueError("ADSENSE_CLIENT should look like ca-pub-1234567890123456.")

    @app.before_request
    def main_address():
        """www.gridglass.in and the old onrender.com address -> https://gridglass.in, same path."""
        host = app.config.get("CANONICAL_HOST")
        if not host or request.method not in ("GET", "HEAD") or request.path == "/healthz":
            return None
        here = request.host.split(":")[0].lower()
        if here != host and (here == f"www.{host}" or here.endswith(".onrender.com")):
            query = f"?{request.query_string.decode()}" if request.query_string else ""
            return redirect(f"https://{host}{request.path}{query}", 301)
        return None

    @app.get("/")
    def index():
        resp = app.response_class(render_template("app.html", site_url=site_url(), adsense_client=client),
                                  mimetype="text/html")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/sw.js")
    def service_worker():  # served from the root so it can control the whole app
        resp = send_from_directory(app.static_folder, "sw.js", max_age=0)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.post("/share")
    @limiter.limit(from_config("RATE_LIMIT_UPLOADS"))
    def share():
        """A file shared from another app (WhatsApp, Files, email…) to the installed app.

        It's uploaded here, then the app opens on the home screen ready for a tool.
        """
        if request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            return redirect("/", 303)  # only the phone's share sheet (or Gridglass itself) may post here
        file = request.files.get("file")
        if file is None or not file.filename:
            return _share_failed("No file came through. Try sharing it again.")
        try:
            meta = store.create(file.stream, file.filename)
        except GridglassError as exc:
            return _share_failed(str(exc))
        return redirect(f"/#/open/{meta['id']}", 303)

    def _share_failed(message: str):
        return redirect(f"/#/open?error={quote(message)}", 303)

    messages = {
        413: f"This file is larger than the {app.config['MAX_UPLOAD_MB']} MB limit.",
        429: "You're going a bit fast — please wait a minute and try again.",
    }

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        if request.path == "/share" and exc.code in messages:
            return _share_failed(messages[exc.code])
        if not request.path.startswith("/api/"):
            if exc.code == 404 and request.method == "GET":
                from .site import page

                resp = page("site/404.html")
                resp.status_code = 404
                resp.headers["Cache-Control"] = "no-cache"
                return resp
            return exc
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
