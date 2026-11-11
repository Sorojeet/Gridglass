"""Information pages, sitemap, robots.txt, ads.txt, the main-address redirect and ad isolation."""
from __future__ import annotations

import re

import pytest

from gridglass import create_app
from gridglass.config import TestConfig
from gridglass.content import GUIDES, TOOLS
from gridglass.engine import OPS
from gridglass.site import BLURB

CLIENT = "ca-pub-1234567890123456"
PAGES = (["/tools", "/guides", "/about", "/contact", "/privacy", "/terms"]
         + [f"/tools/{t.slug}" for t in TOOLS] + [f"/guides/{g.slug}" for g in GUIDES])
AD_HOSTS = ("googlesyndication", "doubleclick", "adsbygoogle")


def make(tmp_path, **kw):
    return create_app(TestConfig, DATA_DIR=tmp_path / "data", **kw).test_client()


@pytest.fixture
def client(tmp_path):
    return make(tmp_path)


@pytest.fixture
def ads(tmp_path):
    return make(tmp_path, ADSENSE_CLIENT=CLIENT, CANONICAL_HOST="gridglass.in")


def test_every_page_renders(client):
    for path in PAGES:
        r = client.get(path)
        assert r.status_code == 200, path
        html = r.get_data(as_text=True)
        assert html.count("<h1") == 1, path
        assert re.search(r'<meta name="description" content="[^"]{40,}">', html), path


def test_every_tool_in_the_app_has_a_page():
    ops = {t.op for t in TOOLS}
    assert ops == set(BLURB)                      # every card in the app, and nothing else
    assert ops - {"convert", "split_pages", "chart", "create"} <= set(OPS)
    assert len({t.slug for t in TOOLS}) == len(TOOLS)


def test_internal_links_all_work(client):
    seen = set()
    for path in PAGES:
        for href in re.findall(r'href="(/[^"#]*)"', client.get(path).get_data(as_text=True)):
            if href in seen or href.startswith("/static/"):
                continue
            seen.add(href)
            assert client.get(href).status_code == 200, f"{href} (linked from {path})"
    assert "/tools/stack-files" in seen and "/privacy" in seen


def test_moved_tool_pages_forward_permanently(client):
    r = client.get("/tools/unpivot")
    assert r.status_code == 301 and r.location.endswith("/tools/transpose")
    html = client.get("/tools/transpose").get_data(as_text=True)
    assert "<h1>Transpose rows and columns in a CSV or Excel file</h1>" in html and 'href="/#/tool/unpivot"' in html


def test_tool_pages_open_the_right_tool(client):
    html = client.get("/tools/remove-duplicates").get_data(as_text=True)
    assert 'href="/#/tool/remove_duplicates"' in html


BRANDS = ("Excel", "VLOOKUP", "XLOOKUP", "Microsoft", "Google Sheets", "Power Query")


def test_each_tool_page_targets_one_search(client):
    """The phrase people type is in the <title>, the <h1> and the first paragraph, and no two pages chase the same one."""
    from gridglass.content import SEARCH

    phrases = [p for p, _, _ in SEARCH.values()]
    assert len(set(map(str.lower, phrases))) == len(phrases)
    for t in TOOLS:
        html = client.get(f"/tools/{t.slug}").get_data(as_text=True)
        phrase = SEARCH[t.slug][0]
        title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
        h1 = re.search(r"<h1>(.*?)</h1>", html, re.S).group(1)
        first = re.search(r"</header>\s*<p>(.*?)</p>", html, re.S).group(1)
        assert title.startswith(phrase) and h1 == phrase, t.slug
        assert phrase.lower() in re.sub(r"<[^>]+>", "", first).lower(), t.slug
        assert phrase.lower() in re.search(r'<meta name="description" content="([^"]*)"', html).group(1).lower(), t.slug


def test_other_brands_only_with_the_trademark_note(client):
    """Other products may be named to say what Gridglass works with, but every such page carries the notice."""
    from gridglass.content import TRADEMARKS

    for path in PAGES:
        html = client.get(path).get_data(as_text=True)
        text = re.sub(r"<[^>]+>", " ", html)
        if any(b in text for b in BRANDS):
            assert TRADEMARKS in html, path


def test_brands_never_name_our_tools():
    """Our own names stay ours: no other product in a tool name or in the site name."""
    from gridglass.content import SITE_NAME

    for t in TOOLS:
        assert not any(b.lower() in t.name.lower() for b in BRANDS), t.name
    assert not any(b.lower() in SITE_NAME.lower() for b in BRANDS)


def test_site_details_are_on_the_legal_pages(client):
    for path in ("/privacy", "/terms", "/about", "/contact"):
        html = client.get(path).get_data(as_text=True)
        assert "hello@gridglass.in" in html and "Mannu" in html, path
    assert "courts at Delhi" in client.get("/terms").get_data(as_text=True)


def test_unknown_pages_are_friendly_404s(client):
    r = client.get("/tools/nope")
    assert r.status_code == 404 and "Page not found" in r.get_data(as_text=True)
    assert '<meta name="robots" content="noindex">' in r.get_data(as_text=True)
    assert client.get("/api/v1/nope").is_json  # the API keeps JSON errors


# --------------------------------------------------------------------------- crawlers

def test_sitemap_lists_every_page_at_the_main_address(ads):
    xml = ads.get("/sitemap.xml").get_data(as_text=True)
    locs = re.findall(r"<loc>([^<]+)</loc>", xml)
    assert "https://gridglass.in/" in locs
    assert {f"https://gridglass.in{p}" for p in PAGES} <= set(locs)


def test_robots(ads):
    text = ads.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /api/" in text and "Sitemap: https://gridglass.in/sitemap.xml" in text


def test_canonical_tags_use_the_main_address(ads):
    assert '<link rel="canonical" href="https://gridglass.in/tools/trim-spaces">' in ads.get("/tools/trim-spaces").get_data(as_text=True)
    assert '<link rel="canonical" href="https://gridglass.in/">' in ads.get("/").get_data(as_text=True)


# --------------------------------------------------------------------------- ads

def test_no_ads_and_no_ads_txt_until_configured(client):
    assert client.get("/ads.txt").status_code == 404
    for path in ("/", "/tools/trim-spaces"):
        html = client.get(path).get_data(as_text=True)
        assert not any(h in html for h in AD_HOSTS) and "google-adsense-account" not in html


def test_ads_txt(ads):
    r = ads.get("/ads.txt")
    assert r.mimetype == "text/plain"
    assert r.get_data(as_text=True) == "google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0\n"


def test_ads_load_only_on_information_pages(ads):
    page = ads.get("/tools/trim-spaces")
    html = page.get_data(as_text=True)
    nonce = re.search(r"'nonce-([^']+)'", page.headers["Content-Security-Policy"]).group(1)
    assert f'adsbygoogle.js?client={CLIENT}" crossorigin="anonymous" nonce="{nonce}"' in html
    assert page.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    app = ads.get("/")  # the app: only the account meta tag, never an ad script
    html = app.get_data(as_text=True)
    assert f'<meta name="google-adsense-account" content="{CLIENT}">' in html
    assert not any(h in html for h in AD_HOSTS)
    assert "script-src 'self'" in app.headers["Content-Security-Policy"] and "https:" not in app.headers["Content-Security-Policy"]
    assert app.headers["Referrer-Policy"] == "no-referrer"


def test_nonce_changes_every_request(ads):
    a = ads.get("/about").headers["Content-Security-Policy"]
    b = ads.get("/about").headers["Content-Security-Policy"]
    assert a != b


def test_bad_adsense_id_is_refused(tmp_path):
    with pytest.raises(ValueError, match="ca-pub-"):
        make(tmp_path, ADSENSE_CLIENT="pub-123")


# --------------------------------------------------------------------------- main address

@pytest.mark.parametrize("host, path, to", [
    ("www.gridglass.in", "/tools?x=1", "https://gridglass.in/tools?x=1"),
    ("gridglass.onrender.com", "/", "https://gridglass.in/"),
    ("gridglass.onrender.com", "/api/v1/tools", "https://gridglass.in/api/v1/tools"),
])
def test_other_addresses_redirect_to_the_main_one(ads, host, path, to):
    r = ads.get(path, base_url=f"https://{host}")
    assert r.status_code == 301 and r.location == to


def test_redirect_leaves_some_requests_alone(ads, client):
    assert ads.get("/healthz", base_url="https://gridglass.onrender.com").status_code == 200  # Render's health check
    assert ads.post("/share", base_url="https://gridglass.onrender.com").status_code != 301   # old installed apps
    assert ads.get("/tools", base_url="https://gridglass.in").status_code == 200
    assert ads.get("/tools", base_url="https://example.com").status_code == 200              # other hosts: untouched
    assert client.get("/tools", base_url="https://www.gridglass.in").status_code == 200       # not configured: untouched


def test_app_help_links_match_the_tool_pages():
    from pathlib import Path

    src = (Path(__file__).parents[1] / "gridglass" / "static" / "js" / "tools.js").read_text()
    block = re.search(r"export const PAGE = \{(.*?)\};", src, re.S).group(1)
    pages = dict(re.findall(r"(\w+): '([\w-]+)'", block))
    assert pages == {t.op: t.slug for t in TOOLS}


def test_version_at_the_bottom_of_every_page(client):
    from gridglass import __version__

    assert f'data-version="{__version__}"' in client.get("/").get_data(as_text=True)
    for path in ("/tools", "/tools/pivot-table", "/about"):
        assert f"Version {__version__}" in client.get(path).get_data(as_text=True), path
