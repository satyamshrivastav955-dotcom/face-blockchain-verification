"""
SSRF and decoded-image safety for candidate downloads. Fully offline: DNS is
replaced by a table and HTTP by a scripted session.
"""

from __future__ import annotations

import struct

import cv2
import numpy as np
import pytest

from src.vision import netguard, preprocess
from src.vision.netguard import UnsafeURLError, is_public_address, resolve_public_addresses, validate_url
from src.vision.preprocess import (
    DownloadError,
    ImageError,
    UnsafeDownloadError,
    decode_image_safely,
    fetch_image,
    load_image,
)

from conftest import make_blob


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """Name -> address table. Anything unlisted resolves to a public address."""
    table = {
        "cdn.example.com": ["93.184.216.34"],
        "evil.example.com": ["10.0.0.5"],
        "mixed.example.com": ["93.184.216.34", "127.0.0.1"],
        "v6.example.com": ["2606:2800:220:1:248:1893:25c8:1946"],
        "v6local.example.com": ["::1"],
        "mapped.example.com": ["::ffff:127.0.0.1"],
        "meta.example.com": ["169.254.169.254"],
    }
    monkeypatch.setattr(netguard, "resolver", lambda host, port: table.get(host, ["93.184.216.34"]))
    return table


class TestUrlValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "",
            " http://cdn.example.com/a.png",
            "http://cdn.example.com/a b.png",
            "file:///etc/passwd",
            "ftp://cdn.example.com/a.png",
            "gopher://cdn.example.com/",
            "javascript:alert(1)",
            "data:image/png;base64,AAAA",
            "//cdn.example.com/a.png",
            "http://",
            "http:///a.png",
            "http://user:pass@cdn.example.com/a.png",
            "http://user@cdn.example.com/a.png",
            "http://cdn.example.com:22/a.png",
            "http://cdn.example.com:8080/a.png",
            "http://cdn.example.com:99999/a.png",
            "http://localhost/a.png",
            "http://LOCALHOST./a.png",
            "http://foo.localhost/a.png",
            "http://printer.local/a.png",
            "http://db.internal/a.png",
            "http://cdn.example.com/" + "a" * 3000,
            "http://cdn.example.com/a\r\nHost: evil",
        ],
    )
    def test_rejected(self, url):
        with pytest.raises(UnsafeURLError):
            validate_url(url)

    @pytest.mark.parametrize(
        "url,port",
        [
            ("http://cdn.example.com/a.png", 80),
            ("https://cdn.example.com/a.png", 443),
            ("https://cdn.example.com:443/a.png", 443),
            ("http://cdn.example.com:80/a", 80),
        ],
    )
    def test_accepted(self, url, port):
        assert validate_url(url).port == port

    @pytest.mark.parametrize(
        "addr,public",
        [
            ("93.184.216.34", True),
            ("8.8.8.8", True),
            ("2606:4700:4700::1111", True),
            ("127.0.0.1", False),
            ("127.1.2.3", False),
            ("10.1.2.3", False),
            ("172.16.0.1", False),
            ("172.31.255.255", False),
            ("192.168.1.1", False),
            ("169.254.169.254", False),
            ("100.64.0.1", False),
            ("0.0.0.0", False),
            ("224.0.0.1", False),
            ("240.0.0.1", False),
            ("255.255.255.255", False),
            ("192.0.2.1", False),
            ("198.18.0.1", False),
            ("::1", False),
            ("::", False),
            ("fe80::1", False),
            ("fc00::1", False),
            ("fd12:3456::1", False),
            ("ff02::1", False),
            ("2001:db8::1", False),
            ("::ffff:127.0.0.1", False),
            ("::ffff:10.0.0.1", False),
            ("::ffff:169.254.169.254", False),
            ("::ffff:93.184.216.34", True),
            ("64:ff9b::7f00:1", False),
            ("2002:7f00:1::", False),
            ("not-an-ip", False),
        ],
    )
    def test_address_classification(self, addr, public):
        assert is_public_address(addr) is public

    @pytest.mark.parametrize(
        "host",
        [
            "evil.example.com",
            "mixed.example.com",
            "v6local.example.com",
            "mapped.example.com",
            "meta.example.com",
            "127.0.0.1",
            "[::1]",
            "10.0.0.1",
        ],
    )
    def test_hosts_resolving_to_non_public_addresses_are_refused(self, host):
        with pytest.raises(UnsafeURLError):
            resolve_public_addresses(host, 80)

    def test_public_hosts_resolve(self):
        assert resolve_public_addresses("cdn.example.com", 443) == ["93.184.216.34"]
        assert resolve_public_addresses("v6.example.com", 443)

    def test_unresolvable_host_is_refused(self, monkeypatch):
        def fail(host, port):
            raise UnsafeURLError("could not resolve")

        monkeypatch.setattr(netguard, "resolver", fail)
        with pytest.raises(UnsafeURLError):
            resolve_public_addresses("nope.example.com", 80)


# -- scripted HTTP session ------------------------------------------------------


def png_bytes(size=64):
    ok, buf = cv2.imencode(".png", make_blob(size))
    assert ok
    return buf.tobytes()


class Resp:
    def __init__(self, status=200, body=b"", headers=None, chunks=None):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks if chunks is not None else [body]

    def iter_content(self, n):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        route = self.routes[url]
        if isinstance(route, Exception):
            raise route
        return route


def ok(body=None, ctype="image/png"):
    return Resp(200, body if body is not None else png_bytes(), {"Content-Type": ctype})


def redirect(to, status=302):
    return Resp(status, headers={"Location": to})


class TestFetchImage:
    def test_successful_fetch_returns_exact_bytes_and_a_decoded_image(self):
        raw = png_bytes()
        s = Session({"https://cdn.example.com/a.png": ok(raw)})
        got, img = fetch_image("https://cdn.example.com/a.png", session=s)
        assert got == raw and img.shape == (64, 64, 3)
        # redirects are handled by us, never by the HTTP library
        assert s.calls[0][1]["allow_redirects"] is False
        assert s.calls[0][1]["timeout"] == preprocess.DOWNLOAD_TIMEOUT

    @pytest.mark.parametrize(
        "url",
        [
            "http://10.0.0.5/a.png",
            "http://127.0.0.1/a.png",
            "http://[::1]/a.png",
            "http://169.254.169.254/latest/meta-data/",
            "http://evil.example.com/a.png",
            "http://meta.example.com/a.png",
            "http://localhost/a.png",
            "file:///etc/passwd",
            "http://u:p@cdn.example.com/a.png",
            "http://cdn.example.com:6379/a.png",
        ],
    )
    def test_unsafe_destinations_never_reach_the_network(self, url):
        s = Session({})
        with pytest.raises(UnsafeDownloadError):
            fetch_image(url, session=s)
        assert s.calls == []

    def test_redirect_to_a_private_address_is_blocked(self):
        s = Session(
            {
                "https://cdn.example.com/a.png": redirect("http://169.254.169.254/latest/meta-data/"),
            }
        )
        with pytest.raises(UnsafeDownloadError):
            fetch_image("https://cdn.example.com/a.png", session=s)
        assert len(s.calls) == 1  # the private hop was never requested

    def test_redirect_to_a_hostname_resolving_privately_is_blocked(self):
        s = Session({"https://cdn.example.com/a.png": redirect("http://evil.example.com/x")})
        with pytest.raises(UnsafeDownloadError):
            fetch_image("https://cdn.example.com/a.png", session=s)

    def test_redirect_to_a_non_http_scheme_is_blocked(self):
        s = Session({"https://cdn.example.com/a.png": redirect("file:///etc/passwd")})
        with pytest.raises(UnsafeDownloadError):
            fetch_image("https://cdn.example.com/a.png", session=s)

    def test_safe_redirect_chain_is_followed_and_relative_redirects_resolve(self):
        s = Session(
            {
                "https://cdn.example.com/a.png": redirect("/b.png", 301),
                "https://cdn.example.com/b.png": redirect("https://cdn.example.com/c.png", 307),
                "https://cdn.example.com/c.png": ok(),
            }
        )
        _, img = fetch_image("https://cdn.example.com/a.png", session=s)
        assert img is not None and len(s.calls) == 3

    def test_redirect_loop(self):
        s = Session(
            {
                "https://cdn.example.com/a": redirect("https://cdn.example.com/b"),
                "https://cdn.example.com/b": redirect("https://cdn.example.com/a"),
            }
        )
        with pytest.raises(DownloadError) as excinfo:
            fetch_image("https://cdn.example.com/a", session=s)
        assert "loop" in str(excinfo.value)

    def test_too_many_redirects(self):
        routes = {f"https://cdn.example.com/{i}": redirect(f"https://cdn.example.com/{i + 1}") for i in range(20)}
        with pytest.raises(DownloadError) as excinfo:
            fetch_image("https://cdn.example.com/0", session=Session(routes))
        assert "redirects" in str(excinfo.value)

    def test_redirect_without_location(self):
        s = Session({"https://cdn.example.com/a": Resp(302)})
        with pytest.raises(DownloadError):
            fetch_image("https://cdn.example.com/a", session=s)

    def test_oversized_declared_length_is_refused_before_reading(self):
        big = Resp(
            200,
            headers={"Content-Type": "image/png", "Content-Length": str(preprocess.MAX_DOWNLOAD_BYTES + 1)},
            chunks=[],
        )
        with pytest.raises(DownloadError) as excinfo:
            fetch_image("https://cdn.example.com/a", session=Session({"https://cdn.example.com/a": big}))
        assert "limit" in str(excinfo.value)

    def test_oversized_stream_without_a_length_header_is_cut_off(self, monkeypatch):
        monkeypatch.setattr(preprocess, "MAX_DOWNLOAD_BYTES", 100_000)
        resp = Resp(200, headers={"Content-Type": "image/png"}, chunks=[b"x" * 60_000] * 5)
        with pytest.raises(DownloadError) as excinfo:
            fetch_image("https://cdn.example.com/a", session=Session({"https://cdn.example.com/a": resp}))
        assert "limit" in str(excinfo.value)

    @pytest.mark.parametrize("ctype", ["text/html", "application/json", "text/plain"])
    def test_non_image_content_types_are_refused(self, ctype):
        s = Session({"https://cdn.example.com/a": ok(b"<html>", ctype)})
        with pytest.raises(DownloadError) as excinfo:
            fetch_image("https://cdn.example.com/a", session=s)
        assert "not an image" in str(excinfo.value)

    def test_invalid_image_body(self):
        s = Session({"https://cdn.example.com/a": ok(b"definitely not an image")})
        with pytest.raises(DownloadError):
            fetch_image("https://cdn.example.com/a", session=s)

    def test_corrupt_png_body(self):
        s = Session({"https://cdn.example.com/a": ok(png_bytes()[:40])})
        with pytest.raises(DownloadError):
            fetch_image("https://cdn.example.com/a", session=s)

    def test_empty_body(self):
        s = Session({"https://cdn.example.com/a": ok(b"")})
        with pytest.raises(DownloadError):
            fetch_image("https://cdn.example.com/a", session=s)

    @pytest.mark.parametrize("status", [403, 404, 429, 500, 503])
    def test_error_statuses(self, status):
        s = Session({"https://cdn.example.com/a": Resp(status)})
        with pytest.raises(DownloadError) as excinfo:
            fetch_image("https://cdn.example.com/a", session=s)
        assert str(status) in str(excinfo.value)

    def test_timeout_is_a_download_error_and_does_not_echo_the_url(self):
        url = "https://cdn.example.com/secret-token-abc123/a.png"
        s = Session({url: TimeoutError("read timed out for " + url)})
        with pytest.raises(DownloadError) as excinfo:
            fetch_image(url, session=s)
        assert "secret-token" not in str(excinfo.value)
        assert "TimeoutError" in str(excinfo.value)

    def test_blocked_error_message_does_not_echo_the_full_url(self):
        with pytest.raises(UnsafeDownloadError) as excinfo:
            fetch_image("http://10.0.0.5/path?token=SECRET", session=Session({}))
        assert "SECRET" not in str(excinfo.value)

    def test_total_deadline(self, monkeypatch):
        clock = iter([0.0, 0.0, 1000.0, 1000.0, 1000.0, 1000.0])
        monkeypatch.setattr(preprocess.time, "monotonic", lambda: next(clock))
        s = Session(
            {"https://cdn.example.com/a": redirect("https://cdn.example.com/b"), "https://cdn.example.com/b": ok()}
        )
        with pytest.raises(DownloadError) as excinfo:
            fetch_image("https://cdn.example.com/a", session=s)
        assert "deadline" in str(excinfo.value)


class TestDecodedImageLimits:
    @staticmethod
    def fake_png_header(width, height):
        return (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IHDR"
            + struct.pack(">II", width, height)
            + b"\x08\x02\x00\x00\x00"
        )

    def test_decompression_bomb_is_refused_before_decoding(self, monkeypatch):
        called = []
        monkeypatch.setattr(preprocess.cv2, "imdecode", lambda *a, **k: called.append(1))
        with pytest.raises(ImageError) as excinfo:
            decode_image_safely(self.fake_png_header(60000, 60000))
        assert "above the limit" in str(excinfo.value) and called == []

    def test_pixel_count_limit_even_when_each_side_is_allowed(self):
        with pytest.raises(ImageError):
            decode_image_safely(self.fake_png_header(15000, 15000))

    def test_zero_dimensions(self):
        with pytest.raises(ImageError):
            decode_image_safely(self.fake_png_header(0, 10))

    def test_unrecognised_formats_are_refused(self):
        for blob in (b"GIF", b"%PDF-1.7", b"II*\x00" + b"\x00" * 40, b"<svg></svg>", b"\x00" * 64):
            with pytest.raises(ImageError):
                decode_image_safely(blob)

    def test_empty(self):
        with pytest.raises(ImageError):
            decode_image_safely(b"")

    def test_valid_formats_round_trip(self):
        img = make_blob(96)
        for ext in (".png", ".jpg", ".bmp", ".webp"):
            ok_, buf = cv2.imencode(ext, img)
            assert ok_
            out = decode_image_safely(buf.tobytes())
            assert out.dtype == np.uint8 and out.shape == (96, 96, 3)

    def test_grayscale_png_is_decoded_to_three_channels(self):
        gray = cv2.cvtColor(make_blob(64), cv2.COLOR_BGR2GRAY)
        _, buf = cv2.imencode(".png", gray)
        assert decode_image_safely(buf.tobytes()).shape == (64, 64, 3)

    def test_load_image_applies_the_same_limits(self, tmp_path):
        p = tmp_path / "bomb.png"
        p.write_bytes(self.fake_png_header(60000, 60000))
        with pytest.raises(ImageError):
            load_image(p)

    def test_load_image_rejects_unsupported_files(self, tmp_path):
        p = tmp_path / "x.png"
        p.write_bytes(b"not an image at all")
        with pytest.raises(ImageError):
            load_image(p)


class TestGuardedSession:
    def test_proxies_and_environment_are_not_trusted(self, monkeypatch):
        monkeypatch.setenv("HTTP_PROXY", "http://attacker.invalid:3128")
        monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid:3128")
        session = netguard.make_guarded_session()
        assert session.trust_env is False and session.proxies == {}
        prepared = session.prepare_request(__import__("requests").Request("GET", "https://cdn.example.com/"))
        assert session.rebuild_proxies(prepared, {}) == {}
        session.close()

    def test_connection_is_pinned_to_the_validated_address(self, monkeypatch):
        """DNS rebinding: the socket must be opened to the checked IP, not re-resolved."""
        opened = []
        import urllib3.util.connection as u3

        monkeypatch.setattr(u3, "create_connection", lambda addr, *a, **k: opened.append(addr) or object())
        http_pool, _ = netguard._build_guarded_classes()
        conn = http_pool.ConnectionCls("cdn.example.com", 80, timeout=5)
        conn._new_conn()
        assert opened == [("93.184.216.34", 80)]

    def test_connection_refuses_when_the_name_now_resolves_privately(self, monkeypatch, dns):
        http_pool, _ = netguard._build_guarded_classes()
        dns["rebind.example.com"] = ["127.0.0.1"]  # answer changed between check and connect
        conn = http_pool.ConnectionCls("rebind.example.com", 80, timeout=5)
        with pytest.raises(UnsafeURLError):
            conn._new_conn()


def test_real_guarded_session_cannot_reach_a_loopback_server():
    """Integration: an actual local HTTP server is unreachable through the guarded session."""
    import http.server
    import threading

    import requests

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # pragma: no cover - must never run
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    try:
        assert requests.get(url, timeout=3).status_code == 200  # control: plain client reaches it
        session = netguard.make_guarded_session()
        with pytest.raises(UnsafeURLError):
            session.get(url, timeout=3)
        session.close()
    finally:
        server.shutdown()
