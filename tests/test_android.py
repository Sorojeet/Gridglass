"""The Play Store app: Digital Asset Links and the Android project's settings."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gridglass import create_app
from gridglass.config import TestConfig

FP = ":".join(["AB"] * 32)
FP2 = ":".join(["0f"] * 32)
ANDROID = Path(__file__).resolve().parent.parent / "android"


def make(tmp_path, **kw):
    return create_app(TestConfig, DATA_DIR=tmp_path / "data", **kw).test_client()


def test_no_assetlinks_until_configured(tmp_path):
    r = make(tmp_path).get("/.well-known/assetlinks.json")
    assert r.status_code == 404 and r.is_json


def test_assetlinks(tmp_path):
    r = make(tmp_path, ANDROID_CERT_SHA256=f"{FP}, {FP2}").get("/.well-known/assetlinks.json")
    assert r.status_code == 200 and r.mimetype == "application/json"
    assert r.get_json() == [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {"namespace": "android_app", "package_name": "com.gridglass.app",
                   "sha256_cert_fingerprints": [FP, FP2.upper()]},
    }]


def test_assetlinks_is_not_redirected_on_the_main_address(tmp_path):
    r = make(tmp_path, ANDROID_CERT_SHA256=FP, CANONICAL_HOST="gridglass.in").get(
        "/.well-known/assetlinks.json", base_url="https://gridglass.in")
    assert r.status_code == 200


@pytest.mark.parametrize("bad", ["AB:CD", "SHA256:" + FP, FP + ":AB", FP.replace("AB", "XY", 1)])
def test_bad_fingerprint_is_refused(tmp_path, bad):
    with pytest.raises(ValueError, match="ANDROID_CERT_SHA256"):
        make(tmp_path, ANDROID_CERT_SHA256=bad)


def test_bad_package_is_refused(tmp_path):
    with pytest.raises(ValueError, match="ANDROID_PACKAGE"):
        make(tmp_path, ANDROID_CERT_SHA256=FP, ANDROID_PACKAGE="gridglass")


def test_android_project_matches_the_site():
    twa = json.loads((ANDROID / "twa-manifest.json").read_text())
    web = json.loads((Path(__file__).resolve().parent.parent / "gridglass/static/manifest.webmanifest").read_text())
    assert twa["packageId"] == TestConfig.ANDROID_PACKAGE
    assert twa["host"] == "gridglass.in" and twa["startUrl"] == web["start_url"]
    assert twa["themeColor"] == web["theme_color"] and twa["backgroundColor"] == web["background_color"]
    assert twa["shareTarget"]["action"] == "https://gridglass.in" + web["share_target"]["action"]
    # Android only understands MIME types in share filters; a bare ".csv" would break the install.
    manifest = (ANDROID / "app/src/main/AndroidManifest.xml").read_text()
    assert 'android:mimeType=".' not in manifest
    gradle = (ANDROID / "app/build.gradle").read_text()
    assert "localhost" not in gradle and "hostName: 'gridglass.in'" in gradle
