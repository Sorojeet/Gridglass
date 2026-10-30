"""Application settings. Override any value with an environment variable of the same name."""
from __future__ import annotations

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

    # Uploads
    MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 50)
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024  # Flask rejects bigger requests with 413
    DATA_DIR = Path(os.environ.get("DATA_DIR", "instance/data"))
    FILE_RETENTION_MINUTES = _int("FILE_RETENTION_MINUTES", 60)
    CLEANUP_INTERVAL_SECONDS = _int("CLEANUP_INTERVAL_SECONDS", 300)  # 0 = off (use `flask purge` from cron)

    # Engine limits
    PREVIEW_ROWS = _int("PREVIEW_ROWS", 200)
    MAX_STEPS = _int("MAX_STEPS", 200)
    MAX_PIVOT_COLUMNS = _int("MAX_PIVOT_COLUMNS", 200)
    MAX_PDF_ROWS = _int("MAX_PDF_ROWS", 10_000)

    # Behind a hosting proxy (Render, Railway, nginx) set TRUST_PROXY=1 so client IPs and https are seen correctly.
    TRUST_PROXY = _int("TRUST_PROXY", 0)

    # Rate limits per client IP (Flask-Limiter syntax). Use Redis for several instances:
    # RATELIMIT_STORAGE_URI=redis://host:6379/0
    RATELIMIT_ENABLED = os.environ.get("RATELIMIT_ENABLED", "1") == "1"
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True
    RATE_LIMIT_API = os.environ.get("RATE_LIMIT_API", "600 per minute")
    RATE_LIMIT_UPLOADS = os.environ.get("RATE_LIMIT_UPLOADS", "10 per minute; 60 per hour")
    RATE_LIMIT_EXPORTS = os.environ.get("RATE_LIMIT_EXPORTS", "30 per minute; 300 per hour")


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"
    CLEANUP_INTERVAL_SECONDS = 0
    RATELIMIT_ENABLED = False
