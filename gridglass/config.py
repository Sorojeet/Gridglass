"""Application settings. Override any value with an environment variable of the same name."""
from __future__ import annotations

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

    # Uploads
    MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 100)
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024  # Flask rejects bigger requests with 413
    DATA_DIR = Path(os.environ.get("DATA_DIR", "instance/data"))
    FILE_RETENTION_MINUTES = _int("FILE_RETENTION_MINUTES", 60)
    CLEANUP_INTERVAL_SECONDS = _int("CLEANUP_INTERVAL_SECONDS", 300)  # 0 = off (use `flask purge` from cron)

    # Engine limits
    PREVIEW_ROWS = _int("PREVIEW_ROWS", 200)           # rows in a preview when the app doesn't ask for more
    PAGE_ROWS = _int("PAGE_ROWS", 1000)                # rows per page when browsing everything
    EDIT_ROWS = _int("EDIT_ROWS", 1000)                # largest table the row editor opens
    BROWSE_MAX_ROWS = _int("BROWSE_MAX_ROWS", 10_000)  # beyond this, download the file to see it all
    MAX_STEPS = _int("MAX_STEPS", 200)
    MAX_PIVOT_COLUMNS = _int("MAX_PIVOT_COLUMNS", 200)
    MAX_PDF_ROWS = _int("MAX_PDF_ROWS", 10_000)

    # The site's main address, e.g. gridglass.in. www.<it> and *.onrender.com then redirect there,
    # and links in the sitemap, canonical tags and robots.txt use it. Empty: no redirects.
    CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "").strip().lower()
    # AdSense client id, e.g. ca-pub-1234567890123456. Empty: no ads and no ads.txt. Ads only ever
    # load on the content pages (/tools, /guides, /about…), never in the app where files are shown.
    ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT", "").strip()

    # The Play Store app (android/). /.well-known/assetlinks.json tells Android that this app may open
    # the site full-screen, without a URL bar. ANDROID_CERT_SHA256 is a comma-separated list of SHA-256
    # signing-certificate fingerprints (AB:CD:…): the Play App Signing key from Play Console, plus the
    # upload key if you install test builds directly. Empty: no assetlinks.json.
    ANDROID_PACKAGE = os.environ.get("ANDROID_PACKAGE", "com.gridglass.app").strip()
    ANDROID_CERT_SHA256 = os.environ.get("ANDROID_CERT_SHA256", "").strip()

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
