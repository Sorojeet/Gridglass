"""Per-IP rate limiting, so one client can't hog the server. Limits come from config at request time."""
from __future__ import annotations

from flask import current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def from_config(key: str):
    return lambda: current_app.config[key]
