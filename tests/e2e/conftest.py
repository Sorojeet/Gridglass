"""End-to-end fixtures: a real Gridglass server on a free port, and a Playwright browser emulating a phone.

Run just these with:  pytest -m e2e
Skip them with:       pytest -m "not e2e"
They need `pip install playwright` and `playwright install chromium`; without those they are skipped.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from gridglass import create_app
from gridglass.config import TestConfig

pw = pytest.importorskip("playwright.sync_api")

# Requests we don't control in CI (web fonts). Blocked so tests are fast, offline and deterministic.
EXTERNAL = ("fonts.googleapis.com", "fonts.gstatic.com")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call":
        item.rep_call = rep


def _save_failure(request, phone):
    rep = getattr(request.node, "rep_call", None)
    if rep is not None and rep.failed:
        out = Path("test-results")
        out.mkdir(exist_ok=True)
        name = "".join(c if c.isalnum() else "_" for c in request.node.nodeid)[-120:]
        try:
            phone.page.screenshot(path=str(out / f"{name}.png"), full_page=True)
        except Exception:
            pass


def pytest_collection_modifyitems(items):
    for item in items:
        if "/e2e/" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    # Point the suite at any running Gridglass (e.g. the Docker image or the live site):
    #   E2E_BASE_URL=https://gridglass.onrender.com pytest -m e2e
    external = os.environ.get("E2E_BASE_URL")
    if external:
        yield external.rstrip("/")
        return
    app = create_app(TestConfig, DATA_DIR=tmp_path_factory.mktemp("e2e-data"))
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="session")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # browsers not installed
            pytest.skip(f"Chromium not available: {exc}")
        yield p, b
        b.close()


def _context(browser, device="iPhone 14", **kw):
    p, b = browser
    opts = {**p.devices[device], "accept_downloads": True, "color_scheme": "light", **kw}
    ctx = b.new_context(**opts)
    ctx.route(lambda url: any(h in url for h in EXTERNAL), lambda route: route.abort())
    return ctx


class Phone:
    """A page plus the JS errors it produced, so every test can assert the console stayed clean."""

    def __init__(self, ctx, base):
        self.ctx, self.base = ctx, base
        self.page = ctx.new_page()
        self.errors: list[str] = []
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("console", self._console)

    def _console(self, msg):
        # 4xx API answers are expected in error tests (the UI shows them as toasts); blocked fonts are ours.
        expected = ("ERR_FAILED", "ERR_BLOCKED", "status of 400", "status of 404", "status of 413", "status of 422")
        if msg.type == "error" and not any(h in msg.text for h in expected):
            self.errors.append(f"console: {msg.text}")

    def open(self, path="/"):
        self.page.goto(self.base + path)
        return self.page

    def upload_sample(self, tool="remove_duplicates"):
        page = self.open(f"/#/tool/{tool}")
        page.click('[data-action="sample"]')
        page.wait_for_selector("#pv table")
        return page


@pytest.fixture
def phone(browser, server, request):
    ctx = _context(browser)
    ph = Phone(ctx, server)
    yield ph
    _save_failure(request, ph)
    ctx.close()
    assert not ph.errors, ph.errors


@pytest.fixture
def make_phone(browser, server, request):
    made = []

    def _make(device="iPhone 14", **kw):
        ph = Phone(_context(browser, device, **kw), server)
        made.append(ph)
        return ph

    yield _make
    for ph in made:
        _save_failure(request, ph)
        ph.ctx.close()
        assert not ph.errors, ph.errors
