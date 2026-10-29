"""
The local web API: real pipeline results, input validation, and local-only guards.

These tests drive the FastAPI app with Starlette's TestClient. Jobs run the real
``run_register`` in demo mode (stub engine + bundled synthetic fixture) so the
suite stays offline; every value asserted below was produced by the pipeline.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("multipart")

from fastapi.testclient import TestClient  # noqa: E402

from src.config import Settings  # noqa: E402
from src.web import app as web_app  # noqa: E402
from src.web.app import create_app  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
QUERY = (DATA / "query.png").read_bytes()
SECRETS = {
    "serpapi_key": "SERPSECRET123456",
    "tineye_api_key": "TINEYESECRET98765",
    "imgbb_api_key": "IMGBBSECRET5555",
    "private_key": "0x" + "ab" * 32,
}


def make_settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.root = tmp_path / "project"
    s.root.mkdir()
    s.search_provider = "local_fixture"
    s.chain_name = "test-chain"
    for key, value in SECRETS.items():
        setattr(s, key, value)
    # real models are not needed in demo mode (stub engine)
    return s


@pytest.fixture
def demo_client(tmp_path):
    app = create_app(make_settings(tmp_path), demo=True)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def strict_client(tmp_path):
    app = create_app(make_settings(tmp_path), demo=False)
    with TestClient(app) as client:
        yield client


def upload(client, data=QUERY, **fields):
    files = {"image": ("whatever.png", io.BytesIO(data), "image/png")}
    return client.post("/api/jobs", files=files, data=fields)


def wait_done(client, job_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


DEMO_FIELDS = {"provider": "local_fixture", "use_demo_engine": "true", "simulate_chain": "true"}


class TestStatusAndGuards:
    def test_health_reports_state_without_secrets(self, strict_client):
        body = strict_client.get("/api/health")
        text = body.text
        assert body.status_code == 200
        for secret in SECRETS.values():
            assert secret not in text
        data = body.json()
        assert data["demo_mode"] is False and data["chain_writes_enabled"] is False
        assert data["search_configured"] is True and data["chain"]["signer_configured"] is True

    def test_unexpected_host_header_is_rejected(self, strict_client):
        assert strict_client.get("/api/health", headers={"Host": "evil.example.com"}).status_code == 400

    def test_cross_origin_post_is_rejected_but_local_origin_is_fine(self, demo_client):
        files = {"image": ("a.png", io.BytesIO(QUERY), "image/png")}
        bad = demo_client.post(
            "/api/jobs", files=files, data=DEMO_FIELDS, headers={"Origin": "https://evil.example.com"}
        )
        assert bad.status_code == 403
        ok = demo_client.post(
            "/api/jobs",
            files={"image": ("a.png", io.BytesIO(QUERY), "image/png")},
            data=DEMO_FIELDS,
            headers={"Origin": "http://localhost:5173"},
        )
        assert ok.status_code == 202

    def test_security_headers(self, strict_client):
        headers = strict_client.get("/api/health").headers
        assert headers["x-content-type-options"] == "nosniff" and headers["cache-control"] == "no-store"

    def test_demo_features_are_refused_outside_demo_mode(self, strict_client):
        assert upload(strict_client, provider="local_fixture").status_code == 403
        assert upload(strict_client, provider="tineye", use_demo_engine="true").status_code == 403
        assert strict_client.get("/api/demo/sample.png").status_code == 404

    def test_real_chain_registration_needs_the_server_flag(self, demo_client):
        assert upload(demo_client, provider="local_fixture", simulate_chain="false").status_code == 403

    def test_unknown_provider(self, demo_client):
        assert upload(demo_client, provider="nonsense").status_code == 422

    def test_upload_validation(self, demo_client, monkeypatch):
        assert upload(demo_client, data=b"", **DEMO_FIELDS).status_code == 422
        assert upload(demo_client, data=b"not an image at all", **DEMO_FIELDS).status_code == 422
        monkeypatch.setattr(web_app, "MAX_UPLOAD_BYTES", 1000)
        too_big = upload(demo_client, data=QUERY, **DEMO_FIELDS)
        assert too_big.status_code == 413

    def test_job_ids_are_validated_and_unknown_ids_404(self, demo_client):
        for bad in ("../etc/passwd", "nothex", "0" * 31, "g" * 32):
            assert demo_client.get(f"/api/jobs/{bad}").status_code in (404, 422)
        assert demo_client.get(f"/api/jobs/{'0' * 32}").status_code == 404
        assert demo_client.delete(f"/api/jobs/{'0' * 32}").status_code == 404

    def test_queue_is_bounded(self, tmp_path, monkeypatch):
        app = create_app(make_settings(tmp_path), demo=True)
        monkeypatch.setattr(app.state.manager._pool, "submit", lambda *a, **k: None)  # never runs
        with TestClient(app) as client:
            codes = [upload(client, **DEMO_FIELDS).status_code for _ in range(8)]
        assert codes[:5] == [202] * 5 and 429 in codes


class TestConsentThroughTheApi:
    def test_external_provider_without_consent_fails_the_job_and_sends_nothing(self, tmp_path, monkeypatch):
        import requests

        def forbidden(*a, **k):
            raise AssertionError("network access attempted")

        for name in ("get", "post", "request"):
            monkeypatch.setattr(requests, name, forbidden)
        settings = make_settings(tmp_path)
        settings.search_provider = "serpapi_lens"
        with TestClient(create_app(settings, demo=True)) as client:
            job = upload(
                client, provider="serpapi_lens", use_demo_engine="true", image_url="https://img.example.com/a.png"
            ).json()
            body = wait_done(client, job["id"])
        assert body["status"] == "failed"
        assert "consent" in body["message"].lower()
        assert body["record"] is None

    def test_disclosure_endpoint_describes_the_data_flow(self, strict_client):
        body = strict_client.get("/api/disclosure", params={"provider": "tineye"}).json()
        assert body["external"] is True and "full query image" in body["items"][0]["what_is_sent"]
        assert strict_client.get("/api/disclosure", params={"provider": "x"}).status_code == 422


class TestRealJobResults:
    @pytest.fixture
    def finished(self, demo_client):
        created = upload(demo_client, **DEMO_FIELDS)
        assert created.status_code == 202
        job_id = created.json()["id"]
        return demo_client, job_id, wait_done(demo_client, job_id)

    def test_status_stages_and_log_come_from_the_pipeline(self, finished):
        _, _, body = finished
        assert body["status"] == "succeeded" and body["exit_code"] == 0
        assert any("Detecting and encoding face" in s for s in body["stages"])
        assert any("Confirming candidates" in s for s in body["stages"])
        assert any("STUB face engine" in line for line in body["log"])  # demo is labelled
        assert body["simulated_chain"] is True and body["demo_mode"] is True

    def test_candidates_and_record_are_the_real_pipeline_output(self, finished):
        _, _, body = finished
        statuses = {c["page_url"]: c["status"] for c in body["candidates"]}
        assert statuses["https://x.com/demo_user/status/1799887766554433221"] == "confirmed_face_match"
        assert statuses["https://example.org/blog/an-unrelated-post"].startswith("rejected")
        record = body["record"]
        assert record["payload"]["evidence_type"] == "face_match"
        assert record["payload"]["test_mode"] == {"stub_engine": True, "offline_fixture_provider": True}
        assert record["anchor"]["simulated"] is True
        assert body["manifest"]["file_count"] >= 5
        assert {"comparison.png", "candidates.json", "manifest.json", "verification.json"} <= set(body["artefacts"])

    def test_artefacts_can_be_downloaded_and_match_the_manifest(self, finished):
        client, job_id, body = finished
        png = client.get(f"/api/jobs/{job_id}/files/comparison.png")
        assert png.status_code == 200 and png.headers["content-type"] == "image/png"
        assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
        record = client.get(f"/api/jobs/{job_id}/files/verification.json").json()
        assert record == body["record"]
        import hashlib

        entry = next(f for f in body["manifest"]["files"] if f["file"] == "comparison.png")
        assert hashlib.sha256(png.content).hexdigest() == entry["sha256"]

    def test_only_whitelisted_artefacts_are_served(self, finished):
        client, job_id, _ = finished
        for name in ("upload.img", "..%2f..%2fupload.img", "search_response.raw.json", "nope.png", "%2e%2e"):
            assert client.get(f"/api/jobs/{job_id}/files/{name}").status_code in (404, 422)

    def test_verify_endpoint_uses_the_real_verifier(self, finished):
        client, job_id, body = finished
        record_bytes = json.dumps(body["record"]).encode()

        def verify(rec, image=None, **fields):
            files = {"record": ("r.json", io.BytesIO(rec), "application/json")}
            if image is not None:
                files["image"] = ("q.png", io.BytesIO(image), "image/png")
            return client.post("/api/verify", files=files, data=fields)

        ok = verify(record_bytes, QUERY, job_id=job_id).json()
        assert ok["verdict"] == "verified" and ok["simulated"] is True
        assert ok["checks"]["image_binding"]["status"] == "pass"
        assert ok["checks"]["url_commitment"]["status"] == "pass"

        other = (DATA / "candidate_other.png").read_bytes()
        bad_image = verify(record_bytes, other, job_id=job_id).json()
        assert bad_image["verdict"] == "local_hash_mismatch"

        forged = json.loads(record_bytes)
        forged["payload"]["match"]["matched_url"] = "https://x.com/attacker/status/1"
        assert verify(json.dumps(forged).encode(), job_id=job_id).json()["verdict"] == "local_hash_mismatch"

        # a record from a simulated chain, checked without that job's chain state
        no_ctx = verify(record_bytes, simulated="true").json()
        assert no_ctx["verdict"] == "not_anchored"

    def test_verify_rejects_malformed_records_with_a_message_not_a_traceback(self, demo_client):
        for payload in (b"{not json", b"[]", b'{"payload": {}}'):
            r = demo_client.post("/api/verify", files={"record": ("r.json", io.BytesIO(payload), "application/json")})
            assert r.status_code == 422 and "Traceback" not in r.text

    def test_delete_removes_the_job_and_its_files(self, finished):
        client, job_id, _ = finished
        manager = client.app.state.manager
        directory = manager.get(job_id).dir
        assert directory.exists()
        assert client.delete(f"/api/jobs/{job_id}").status_code == 200
        assert not directory.exists()
        assert client.get(f"/api/jobs/{job_id}").status_code == 404

    def test_shutdown_removes_all_temporary_files(self, tmp_path):
        app = create_app(make_settings(tmp_path), demo=True)
        with TestClient(app) as client:
            job_id = upload(client, **DEMO_FIELDS).json()["id"]
            wait_done(client, job_id)
            directory = app.state.manager.get(job_id).dir
            assert directory.exists()
        assert not directory.exists()

    def test_no_match_is_reported_as_such(self, demo_client):
        other = (DATA / "candidate_other.png").read_bytes()
        job = upload(demo_client, data=other, **DEMO_FIELDS).json()
        body = wait_done(demo_client, job["id"])
        # the stub engine scores the unrelated pattern against its own copy in the fixture
        assert body["status"] in ("succeeded", "no_match")
        if body["status"] == "no_match":
            assert body["record"] is None and "Nothing was registered" in body["message"]


def test_demo_sample_is_the_real_fixture_file(demo_client):
    assert demo_client.get("/api/demo/sample.png").content == QUERY


def test_internal_errors_do_not_leak_details(tmp_path, monkeypatch):
    app = create_app(make_settings(tmp_path), demo=True)
    monkeypatch.setattr(
        app.state.manager, "get", lambda job_id: (_ for _ in ()).throw(RuntimeError("secret path C:/x"))
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get(f"/api/jobs/{'a' * 32}")
    assert r.status_code == 500 and "secret path" not in r.text
