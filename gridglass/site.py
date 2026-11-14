"""The pages search engines read: tool pages, guides, About/Contact/Privacy/Terms, plus sitemap,
robots.txt and ads.txt.

Ads (when ADSENSE_CLIENT is set) only ever load on these pages. The app itself, where people's
files are shown, never loads an ad script, so no third party can read a file's contents.
"""
from __future__ import annotations

import re
import secrets
from datetime import date

from flask import Blueprint, Response, abort, current_app, g, redirect, render_template, request, url_for
from markupsafe import Markup

from . import content
from .content import CATEGORIES, GUIDE_BY_SLUG, GUIDES, TOOL_BY_SLUG, TOOLS

bp = Blueprint("site", __name__)


def _icons() -> tuple[dict[str, str], dict[str, str]]:
    """Tool icons, read from the app's catalogue (static/js/tools.js) so there is one source of truth."""
    from pathlib import Path

    src = (Path(__file__).parent / "static" / "js" / "tools.js").read_text(encoding="utf-8")
    paths = dict(re.findall(r"^  (\w+): '(<[^']+)',$", src, flags=re.M))
    by_op = dict(re.findall(r"op: '(\w+)', cat: '\w+', icon: '(\w+)'", src))
    blurbs = {op: a or b for op, a, b in
              re.findall(r"op: '(\w+)', cat:[^\n]*\n\s*desc: (?:'([^']*)'|\"([^\"]*)\")", src)}
    return paths, by_op, blurbs


_PATHS, _ICON_OF, BLURB = _icons()


def icon(name: str, cls: str = "") -> Markup:
    return Markup(f'<svg class="ico {cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                  f'{_PATHS.get(name, "")}</svg>')


def tool_icon(op: str) -> Markup:
    return icon(_ICON_OF.get(op, op))

LASTMOD = date(2026, 11, 14)
PAGES = [("site.about", "About"), ("site.contact", "Contact"), ("site.privacy", "Privacy"), ("site.terms", "Terms")]

#: Content pages with ads. Google's ad and consent scripts load other scripts, frames and images
#: from many Google hosts, so the policy trusts scripts by nonce (and what they load), as Google
#: recommends, instead of listing hosts.
AD_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'nonce-{nonce}' 'strict-dynamic' https: 'unsafe-inline'",  # https:/unsafe-inline only for old browsers
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "font-src 'self' https:",
    "connect-src 'self' https:",
    "frame-src https:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def site_url() -> str:
    """https://gridglass.in in production (CANONICAL_HOST), else whatever host served this request."""
    host = current_app.config.get("CANONICAL_HOST")
    return f"https://{host}" if host else request.url_root.rstrip("/")


def ads_enabled() -> bool:
    return bool(current_app.config.get("ADSENSE_CLIENT"))


def page(template: str, **ctx):
    """Render a content page with the shared context, and the ad-friendly policy when ads are on."""
    g.nonce = secrets.token_urlsafe(16)
    html = render_template(template, site=content, site_url=site_url(), path=request.path, nonce=g.nonce,
                           ads=ads_enabled(), adsense_client=current_app.config.get("ADSENSE_CLIENT", ""),
                           categories=CATEGORIES, tools=TOOLS, guides=GUIDES, pages=PAGES,
                           tool_by_slug=TOOL_BY_SLUG, year=date.today().year, icon=icon, tool_icon=tool_icon, blurb=BLURB,
                           retention=current_app.config["FILE_RETENTION_MINUTES"],
                           max_mb=current_app.config["MAX_UPLOAD_MB"], **ctx)
    resp = Response(html, mimetype="text/html")
    if ads_enabled():
        resp.headers["Content-Security-Policy"] = AD_CSP.format(nonce=g.nonce)
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"  # ad requests need the page's origin
    resp.headers["Cache-Control"] = "public, max-age=600"
    return resp


@bp.get("/tools")
def tools_index():
    return page("site/tools.html")


@bp.get("/tools/<slug>")
def tool(slug):
    if slug in content.MOVED:  # an old address: keep links and search results working
        return redirect(url_for("site.tool", slug=content.MOVED[slug]), code=301)
    t = TOOL_BY_SLUG.get(slug) or abort(404)
    return page("site/tool.html", tool=t, related=[TOOL_BY_SLUG[s] for s in t.related if s in TOOL_BY_SLUG],
                guides_for=[gd for gd in GUIDES if slug in gd.tools])


@bp.get("/guides")
def guides_index():
    return page("site/guides.html")


@bp.get("/guides/<slug>")
def guide(slug):
    gd = GUIDE_BY_SLUG.get(slug) or abort(404)
    return page("site/guide.html", guide=gd, used=[TOOL_BY_SLUG[s] for s in gd.tools if s in TOOL_BY_SLUG])


@bp.get("/about")
def about():
    return page("site/about.html")


@bp.get("/contact")
def contact():
    return page("site/contact.html")


@bp.get("/privacy")
def privacy():
    return page("site/privacy.html")


@bp.get("/terms")
def terms():
    return page("site/terms.html")


# --------------------------------------------------------------------------- for crawlers

@bp.get("/sitemap.xml")
def sitemap():
    base = site_url()
    paths = (["/", url_for("site.tools_index"), url_for("site.guides_index")]
             + [url_for("site.tool", slug=t.slug) for t in TOOLS]
             + [url_for("site.guide", slug=gd.slug) for gd in GUIDES]
             + [url_for(endpoint) for endpoint, _ in PAGES])
    urls = "".join(f"<url><loc>{base}{p}</loc><lastmod>{LASTMOD.isoformat()}</lastmod></url>" for p in paths)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, mimetype="application/xml")


@bp.get("/robots.txt")
def robots():
    body = f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /share\n\nSitemap: {site_url()}/sitemap.xml\n"
    return Response(body, mimetype="text/plain")


@bp.get("/ads.txt")
def ads_txt():
    client = current_app.config.get("ADSENSE_CLIENT", "")
    if not client:
        abort(404)
    publisher = client.removeprefix("ca-")  # ca-pub-123 -> pub-123
    return Response(f"google.com, {publisher}, DIRECT, f08c47fec0942fa0\n", mimetype="text/plain")
