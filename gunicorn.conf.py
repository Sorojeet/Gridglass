"""gunicorn settings. Every value can be overridden with an environment variable."""
import os
import re

from gunicorn.glogging import Logger

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# A few processes, each with threads: uploads and exports are I/O-heavy, and Polars does its own threading.
workers = int(os.environ.get("WEB_CONCURRENCY", 2))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 4))

# Big files on slow phone connections need time; a stuck worker is still recycled.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 120))
graceful_timeout = 30
keepalive = 5

# Restart workers now and then so memory from large files is always returned to the system.
max_requests = 500
max_requests_jitter = 100

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

_FILE_ID = re.compile(r"/files/[A-Za-z0-9_-]{22}")


class RedactingLogger(Logger):
    """Upload ids are the only key to a user's file, so they never appear in access logs."""

    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        for key in ("r", "U"):
            if isinstance(atoms.get(key), str):
                atoms[key] = _FILE_ID.sub("/files/<id>", atoms[key])
        return atoms


logger_class = RedactingLogger
