"""
External-processing consent, evidence retention, and record/bundle hardening.
Nothing here touches the network: any attempt to would fail the test.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.config import Settings
from src.evidence.bundle import EvidenceBundle, verify_bundle
from src.evidence.hashing import sha256_bytes
from src.evidence.record import (
    MAX_RECORD_BYTES,
    RecordError,
    build_payload,
    load_record,
    save_record,
    seal,
    validate_record,
)
from src.main import main
from src.pipeline import EXIT_ERROR, run_register
from src.privacy import ConsentError, disclosure_for, purge_evidence, require_consent
from src.search import SearchResult
from src.ui import Console


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if anything tries to send data out."""
    import requests

    def forbidden(*a, **k):
        raise AssertionError("network access attempted without consent")

    for name in ("get", "post", "request"):
        monkeypatch.setattr(requests, name, forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    return forbidden


@pytest.fixture
def real_provider_settings(settings):
    settings.search_provider = "serpapi_lens"
    settings.serpapi_key = "test-key-not-real"
    return settings


def register_real(settings, image, **kwargs):
    import src.pipeline as pipeline

    return run_register(
        settings,
        image,
        provider_name="serpapi_lens",
        engine_name="stub",
        allow_offline_stub=True,
        dry_run=True,
        console=Console(force_ascii=True),
        **kwargs,
    ), pipeline


class TestConsentGate:
    def test_defaults_are_privacy_safe(self):
        assert Settings().publish_provider == "none"
        from src.config import load_settings

        assert load_settings(Path(os.devnull)).publish_provider in ("none", os.environ.get("PUBLISH_PROVIDER", "none"))

    def test_external_search_needs_consent(self, real_provider_settings, query_image, no_network, capsys):
        code, _ = register_real(real_provider_settings, query_image, image_url="https://img.example.com/a.png")
        out = capsys.readouterr().out
        assert code == EXIT_ERROR
        assert "explicit consent" in out and "--consent-external-search" in out
        assert "nothing has been sent" in out

    def test_public_upload_needs_its_own_consent(self, real_provider_settings, query_image, no_network, capsys):
        real_provider_settings.publish_provider = "catbox"
        code, _ = register_real(real_provider_settings, query_image, consent_external_search=True)
        out = capsys.readouterr().out
        assert code == EXIT_ERROR
        assert "--consent-public-upload" in out and "catbox.moe" in out

    def test_consent_to_upload_but_provider_none_fails_actionably_without_uploading(
        self, real_provider_settings, query_image, no_network, capsys
    ):
        code, _ = register_real(
            real_provider_settings,
            query_image,
            consent_external_search=True,
            consent_public_upload=True,
        )
        out = capsys.readouterr().out
        assert code == EXIT_ERROR
        assert "PUBLISH_PROVIDER is 'none'" in out and "--image-url" in out
        assert "published at" not in out

    def test_with_consent_the_search_runs_once_and_data_flow_is_disclosed(
        self, real_provider_settings, query_image, monkeypatch, capsys
    ):
        import src.search.serpapi_lens as lens

        calls = []

        def fake_search(self, image_path, *, image_url="", max_results=25):
            calls.append(image_url)
            return SearchResult(
                provider=self.name,
                endpoint="x",
                searched_at="2026-01-01T00:00:00Z",
                candidates=[],
                raw_response={"stub": True},
            )

        monkeypatch.setattr(lens.SerpApiLensProvider, "search", fake_search)
        code, _ = register_real(
            real_provider_settings,
            query_image,
            image_url="https://img.example.com/a.png",
            consent_external_search=True,
        )
        out = capsys.readouterr().out
        assert calls == ["https://img.example.com/a.png"]
        assert "EXTERNAL PROCESSING" in out and "SerpApi" in out
        assert code == 5  # empty result: an honest "no match", after consented search

    def test_provider_failure_is_not_reported_as_no_match(
        self, real_provider_settings, query_image, monkeypatch, capsys
    ):
        import src.search.serpapi_lens as lens
        from src.search import SearchError

        def fail(self, *a, **k):
            raise SearchError("SerpApi quota exhausted (HTTP 429)")

        monkeypatch.setattr(lens.SerpApiLensProvider, "search", fail)
        code, _ = register_real(
            real_provider_settings,
            query_image,
            image_url="https://img.example.com/a.png",
            consent_external_search=True,
        )
        out = capsys.readouterr().out
        assert code == EXIT_ERROR and "technical failure" in out
        assert not (real_provider_settings.output_dir / "verification.json").exists()

    def test_offline_fixture_needs_no_consent_and_sends_nothing(self, settings, scene, no_network):
        settings.fixture_path = str(scene["fixture"])
        code = run_register(
            settings,
            scene["query"],
            provider_name="local_fixture",
            engine_name="stub",
            allow_offline_stub=True,
            dry_run=True,
            console=Console(force_ascii=True),
        )
        assert code == 0

    def test_cli_search_refuses_without_consent(self, tmp_path, query_image, no_network, capsys, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("SEARCH_PROVIDER=serpapi_lens\nSERPAPI_KEY=k\n", encoding="utf-8")
        monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        code = main(
            [
                "search",
                "--image",
                str(query_image),
                "--env",
                str(env),
                "--ascii",
                "--image-url",
                "https://img.example.com/a.png",
            ]
        )
        assert code == 1 and "--consent-external-search" in capsys.readouterr().out

    def test_tineye_discloses_that_the_file_itself_is_sent(self):
        items = disclosure_for("tineye", needs_public_url=False, publish_provider="none", have_image_url=False)
        assert len(items) == 1 and "full query image file" in items[0].what_is_sent

    def test_require_consent_returns_empty_for_offline(self):
        assert (
            require_consent(
                provider_name="local_fixture",
                is_offline_stub=True,
                needs_public_url=False,
                publish_provider="catbox",
                have_image_url=False,
                consent_external_search=False,
                consent_public_upload=False,
            )
            == []
        )

    def test_consent_error_lists_every_missing_flag(self):
        with pytest.raises(ConsentError) as excinfo:
            require_consent(
                provider_name="serpapi_google_lens",
                is_offline_stub=False,
                needs_public_url=True,
                publish_provider="uguu",
                have_image_url=False,
                consent_external_search=False,
                consent_public_upload=False,
            )
        text = str(excinfo.value)
        assert "--consent-public-upload" in text and "--consent-external-search" in text


class TestSecretsAreNotPrinted:
    def test_doctor_never_prints_secrets_or_rpc_paths(self, tmp_path, monkeypatch, capsys):
        env = tmp_path / ".env"
        env.write_text(
            "SERPAPI_KEY=SECRETSERP1234567890\nTINEYE_API_KEY=SECRETTINEYE98765\n"
            "IMGBB_API_KEY=SECRETIMGBB555555\n"
            "PRIVATE_KEY=0x" + "ab" * 32 + "\nRPC_URL=https://rpc.example.com/v2/SECRETRPCKEY\n",
            encoding="utf-8",
        )
        for var in ("SERPAPI_KEY", "TINEYE_API_KEY", "IMGBB_API_KEY", "PRIVATE_KEY", "RPC_URL"):
            monkeypatch.delenv(var, raising=False)
        main(["doctor", "--offline", "--ascii", "--env", str(env)])
        out = capsys.readouterr().out
        for secret in ("SECRETSERP", "SECRETTINEYE", "SECRETIMGBB", "SECRETRPCKEY", "ab" * 16):
            assert secret not in out
        assert "set (" in out and "chars)" in out

    def test_provider_errors_do_not_leak_keys(self, monkeypatch):
        import requests
        from src.search import SearchError
        from src.search.serpapi_lens import SerpApiLensProvider

        def boom(url, params=None, timeout=None):
            raise requests.ConnectionError(f"failed for {url}?api_key={params['api_key']}")

        monkeypatch.setattr(requests, "get", boom)
        with pytest.raises(SearchError) as excinfo:
            SerpApiLensProvider("SECRETKEY123").search(Path("x.png"), image_url="https://a/b.png")
        assert "SECRETKEY123" not in str(excinfo.value)


class TestRetention:
    def make_runs(self, root: Path):
        old = root / "20200101T000000Z_abcd1234"
        new = root / "29990101T000000Z_abcd1234"
        stray = root / "notes"
        for d in (old, new, stray):
            d.mkdir(parents=True)
            (d / "f").write_text("x", encoding="utf-8")
        past = time.time() - 40 * 86400
        os.utime(old, (past, past))
        os.utime(stray, (past, past))
        return old, new, stray

    def test_dry_run_deletes_nothing(self, tmp_path):
        old, new, stray = self.make_runs(tmp_path)
        assert purge_evidence(tmp_path, older_than_days=30) == [old]
        assert old.exists()

    def test_deletes_only_old_run_directories(self, tmp_path):
        old, new, stray = self.make_runs(tmp_path)
        assert purge_evidence(tmp_path, older_than_days=30, dry_run=False) == [old]
        assert not old.exists() and new.exists() and stray.exists()

    def test_symlinks_are_never_followed(self, tmp_path):
        target = tmp_path / "keep"
        target.mkdir()
        (target / "important").write_text("x", encoding="utf-8")
        link = tmp_path / "20200101T000000Z_abcd1234"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable")
        assert purge_evidence(tmp_path, older_than_days=0, dry_run=False) == []
        assert (target / "important").exists()

    def test_missing_directory_and_bad_argument(self, tmp_path):
        assert purge_evidence(tmp_path / "nope", older_than_days=1) == []
        with pytest.raises(ValueError):
            purge_evidence(tmp_path, older_than_days=-1)

    def test_cli_purge_is_a_dry_run_by_default(self, tmp_path, capsys, monkeypatch):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        self.make_runs(evidence)
        env = tmp_path / ".env"
        env.write_text("", encoding="utf-8")
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        assert main(["purge-evidence", "--older-than-days", "30", "--ascii", "--env", str(env)]) == 0
        assert "would delete 20200101T000000Z_abcd1234" in capsys.readouterr().out
        assert (evidence / "20200101T000000Z_abcd1234").exists()


# -- record loading ----------------------------------------------------------


def good_record():
    payload = build_payload(
        source_image={"filename": "a.png", "sha256": "0" * 64},
        face={"engine": "x"},
        search={"provider": "x"},
        match={"matched_url": "https://x.com/a/1", "decision_rule": "confirmed_face_match"},
        created_at="2026-01-01T00:00:00Z",
    )
    return seal(payload)


class TestRecordLoading:
    @pytest.mark.parametrize(
        "content",
        [
            "",
            "{not json",
            "[]",
            "null",
            '"string"',
            "42",
            '{"payload": {}}',
            '{"payload": [], "integrity": {}}',
            '{"payload": {}, "integrity": []}',
            '{"payload": {}, "integrity": {"verification_hash": "0xabc"}, "schema": "faceverify/v2"}',
            '{"payload": {}, "integrity": {"verification_hash": 5}, "schema": "faceverify/v2"}',
            '{"payload": {}, "integrity": {"verification_hash": "0x' + "g" * 64 + '"}, "schema": "faceverify/v2"}',
            '{"payload": {}, "integrity": {"verification_hash": "0x' + "a" * 64 + '"}, "schema": "faceverify/v9"}',
            '{"payload": {"match": 5}, "integrity": {"verification_hash": "0x'
            + "a" * 64
            + '"}, "schema": "faceverify/v2"}',
            '{"payload": {"match": {"matched_url": 5}}, "integrity": {"verification_hash": "0x'
            + "a" * 64
            + '"}, "schema": "faceverify/v2"}',
            '{"payload": {}, "integrity": {"verification_hash": "0x'
            + "a" * 64
            + '"}, "schema": "faceverify/v2", "anchor": 5}',
            '{"payload": {"x": NaN}, "integrity": {"verification_hash": "0x'
            + "a" * 64
            + '"}, "schema": "faceverify/v2"}',
        ],
    )
    def test_malformed_records_raise_record_error(self, tmp_path, content):
        path = tmp_path / "r.json"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(RecordError):
            load_record(path)

    def test_invalid_utf8(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_bytes(b"\xff\xfe\x00bad")
        with pytest.raises(RecordError):
            load_record(path)

    def test_oversized_record(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_bytes(b" " * (MAX_RECORD_BYTES + 1))
        with pytest.raises(RecordError):
            load_record(path)

    def test_deeply_nested_json_is_a_record_error_not_a_crash(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
        with pytest.raises(RecordError):
            load_record(path)

    def test_directory_is_not_a_record(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_record(tmp_path)

    def test_valid_record_round_trips(self, tmp_path):
        record = good_record()
        path = save_record(record, tmp_path / "r.json")
        assert load_record(path) == record

    def test_validate_accepts_both_supported_schemas(self):
        for schema in ("faceverify/v1", "faceverify/v2"):
            record = good_record()
            record["schema"] = schema
            validate_record(record)


# -- evidence bundle -----------------------------------------------------------


@pytest.fixture
def bundle(tmp_path):
    b = EvidenceBundle(tmp_path / "evidence", "20260101T000000Z_abcd1234")
    b.write_bytes("search_response.raw.json", b'{"raw": true}')
    b.write_bytes("candidates.canonical.json", b'[{"page_url":"https://x.com/a/1"}]')
    b.write_json(
        "candidates.json",
        [
            {
                "page_url": "https://x.com/a/1",
                "image_url": "https://c/i.jpg",
                "status": "confirmed_face_match",
                "candidate_image_sha256": sha256_bytes(b"imagebytes"),
            }
        ],
    )
    b.write_bytes("matched_image.original", b"imagebytes")
    b.finalize()
    return b


def matching_record(bundle):
    record = good_record()
    payload = record["payload"]
    payload["search"] = {
        "candidates_sha256": sha256_bytes(b'[{"page_url":"https://x.com/a/1"}]'),
        "raw_response_sha256": sha256_bytes(b'{"raw": true}'),
    }
    payload["match"] = {
        "matched_url": "https://x.com/a/1",
        "matched_image_url": "https://c/i.jpg",
        "decision_rule": "confirmed_face_match",
        "matched_image_sha256": sha256_bytes(b"imagebytes"),
    }
    return record


class TestBundleIntegrity:
    def test_clean_bundle_passes(self, bundle):
        result = verify_bundle(bundle.dir)
        assert result.ok and result.files_checked == 4

    def test_modified_file_is_detected(self, bundle):
        (bundle.dir / "candidates.json").write_text("[]", encoding="utf-8")
        result = verify_bundle(bundle.dir)
        assert not result.ok and any("modified" in p for p in result.problems)

    def test_deleted_file_is_detected(self, bundle):
        (bundle.dir / "matched_image.original").unlink()
        assert any("missing" in p for p in verify_bundle(bundle.dir).problems)

    def test_extra_file_is_detected(self, bundle):
        (bundle.dir / "extra.png").write_bytes(b"x")
        assert any("not listed" in p for p in verify_bundle(bundle.dir).problems)

    def test_missing_manifest(self, tmp_path):
        assert not verify_bundle(tmp_path).ok

    @pytest.mark.parametrize("name", ["../outside", "..\\outside", "/etc/passwd", "a/b", "C:evil", ""])
    def test_path_confusion_in_the_manifest_is_rejected(self, bundle, name):
        manifest = json.loads((bundle.dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["files"].append({"file": name, "sha256": "0" * 64})
        (bundle.dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert any("unsafe" in p for p in verify_bundle(bundle.dir).problems)

    @pytest.mark.parametrize("content", ["{", "[]", '{"files": 5}', '{"files": [5]}'])
    def test_malformed_manifest_does_not_crash(self, bundle, content):
        (bundle.dir / "manifest.json").write_text(content, encoding="utf-8")
        assert not verify_bundle(bundle.dir).ok

    def test_record_and_bundle_cross_check_passes(self, bundle):
        assert verify_bundle(bundle.dir, matching_record(bundle)).ok

    def test_swapped_raw_response_is_caught_against_the_record(self, bundle):
        record = matching_record(bundle)
        bundle.write_bytes("search_response.raw.json", b'{"raw": "swapped"}')
        bundle.finalize()  # an attacker can regenerate the manifest...
        result = verify_bundle(bundle.dir, record)  # ...but not the sealed record
        assert not result.ok and any("raw_response_sha256" in p for p in result.problems)

    def test_candidate_table_must_contain_the_matched_candidate(self, bundle):
        record = matching_record(bundle)
        record["payload"]["match"]["matched_url"] = "https://x.com/someone-else/9"
        assert any("not in candidates.json" in p for p in verify_bundle(bundle.dir, record).problems)

    def test_candidate_status_must_agree_with_the_decision_rule(self, bundle):
        record = matching_record(bundle)
        record["payload"]["match"]["decision_rule"] = "confirmed_image_derivative"
        assert any("disagrees" in p for p in verify_bundle(bundle.dir, record).problems)

    def test_cli_verify_with_evidence_dir(self, settings, scene, capsys):
        from src.pipeline import run_verify

        settings.fixture_path = str(scene["fixture"])
        assert (
            run_register(
                settings,
                scene["query"],
                provider_name="local_fixture",
                engine_name="stub",
                allow_offline_stub=True,
                dry_run=True,
                console=Console(force_ascii=True),
            )
            == 0
        )
        run_dir = sorted(p for p in settings.evidence_dir.iterdir() if p.is_dir())[-1]
        report: dict = {}
        record_path = settings.output_dir / "verification.json"
        code = run_verify(
            settings, record_path, dry_run=True, evidence_dir=run_dir, console=Console(force_ascii=True), report=report
        )
        assert code == 0 and report["checks"]["evidence_bundle"]["status"] == "pass"

        (run_dir / "candidates.json").write_text("[]", encoding="utf-8")
        code = run_verify(
            settings, record_path, dry_run=True, evidence_dir=run_dir, console=Console(force_ascii=True), report=report
        )
        assert code == 2 and report["checks"]["evidence_bundle"]["status"] == "fail"
