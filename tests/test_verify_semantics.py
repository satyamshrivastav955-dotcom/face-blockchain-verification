"""
Verification must fail closed.

"Verified" is reported only when every check the claim needs actually ran and
passed. A check that could not run (RPC down, incompatible contract, failed
commitment lookup) is INCONCLUSIVE - never a pass, and never silently skipped.
"""

from __future__ import annotations

import json

import pytest

from src.blockchain.client import ChainError, ChainRecord, IncompatibleContractError
from src.config import ConfigError
from src.evidence.record import (
    INTEGRITY_ALGORITHM,
    Status,
    check_local_integrity,
    load_record,
    mutate_payload,
    save_record,
    seal,
)
from src.main import main
from src.pipeline import run_register, run_verify
from src.ui import Console

from conftest import make_blob  # noqa: F401  (keeps conftest import side effects consistent)


def register(settings, scene):
    settings.fixture_path = str(scene["fixture"])
    code = run_register(
        settings,
        scene["query"],
        provider_name="local_fixture",
        engine_name="stub",
        dry_run=True,
        allow_offline_stub=True,
        console=Console(force_ascii=True),
    )
    assert code == 0
    return settings.output_dir / "verification.json"


class FakeClient:
    """A chain client whose every method can be scripted to fail."""

    simulated = False
    network, chain_id = "fake", 1

    def __init__(self, record, *, lookup=None, matches=True):
        self._record = record
        self._lookup = lookup
        self._matches = matches

    def describe(self):
        return {"network": "fake", "chain_id": 1, "contract_address": "0x" + "ab" * 20, "registry_version": 2}

    def lookup(self, data_hash):
        if isinstance(self._lookup, Exception):
            raise self._lookup
        return self._lookup or ChainRecord(
            exists=True, submitter="0x" + "11" * 20, timestamp=1_700_000_000, block_number=7
        )

    def matches_url(self, data_hash, url):
        if isinstance(self._matches, Exception):
            raise self._matches
        return self._matches


@pytest.fixture
def record_path(settings, scene):
    return register(settings, scene)


def verify(settings, path, client=None, monkeypatch=None, **kwargs):
    import src.pipeline as pipeline

    if client is not None:
        monkeypatch.setattr(pipeline, "build_chain_client", lambda *a, **k: client)
    report: dict = {}
    code = run_verify(settings, path, console=Console(force_ascii=True), report=report, **kwargs)
    return code, report


class TestFailClosed:
    def test_all_checks_pass(self, settings, record_path, monkeypatch):
        code, report = verify(settings, record_path, FakeClient(None), monkeypatch)
        assert code == 0 and report["verdict"] == "verified"
        assert report["checks"]["chain_anchor"]["status"] == "pass"
        assert report["checks"]["url_commitment"]["status"] == "pass"
        assert report["checks"]["image_binding"]["status"] == "skipped"

    def test_url_commitment_failure_is_not_success(self, settings, record_path, monkeypatch, capsys):
        """The old code caught this exception and reported success."""
        client = FakeClient(None, matches=ChainError("URL commitment check failed: boom"))
        code, report = verify(settings, record_path, client, monkeypatch)
        assert code == Status.INCONCLUSIVE.exit_code == 6
        assert report["verdict"] == "inconclusive"
        assert report["checks"]["chain_anchor"]["status"] == "pass"
        assert report["checks"]["url_commitment"]["status"] == "error"
        out = capsys.readouterr().out
        assert "RECORD VERIFIED" not in out and "INCONCLUSIVE" in out

    def test_unexpected_exception_in_the_commitment_check_is_inconclusive(self, settings, record_path, monkeypatch):
        client = FakeClient(None, matches=RuntimeError("weird"))
        code, report = verify(settings, record_path, client, monkeypatch)
        assert code == 6 and report["checks"]["url_commitment"]["status"] == "error"

    def test_url_mismatch_with_matching_hash_is_a_failure(self, settings, record_path, monkeypatch):
        code, report = verify(settings, record_path, FakeClient(None, matches=False), monkeypatch)
        assert code == Status.ANCHOR_MISMATCH.exit_code == 4
        assert report["verdict"] == "anchor_mismatch"
        assert report["checks"]["chain_anchor"]["status"] == "pass"
        assert report["checks"]["url_commitment"]["status"] == "fail"

    def test_chain_lookup_failure_is_inconclusive(self, settings, record_path, monkeypatch):
        client = FakeClient(None, lookup=ChainError("chain lookup failed: timeout"))
        code, report = verify(settings, record_path, client, monkeypatch)
        assert code == 6
        assert report["checks"]["chain_anchor"]["status"] == "error"
        assert report["checks"]["url_commitment"]["status"] == "error"
        assert report["checks"]["local_integrity"]["status"] == "pass"

    def test_incompatible_contract_is_inconclusive(self, settings, record_path, monkeypatch):
        import src.pipeline as pipeline

        def build(*a, **k):
            raise IncompatibleContractError("v1 registry")

        monkeypatch.setattr(pipeline, "build_chain_client", build)
        code, report = verify(settings, record_path)
        assert code == 6 and "v1 registry" in report["message"]

    def test_unreachable_chain_is_inconclusive(self, settings, record_path, monkeypatch):
        import src.pipeline as pipeline

        def build(*a, **k):
            raise ChainError("cannot reach the RPC endpoint")

        monkeypatch.setattr(pipeline, "build_chain_client", build)
        code, report = verify(settings, record_path)
        assert code == 6 and report["verdict"] == "inconclusive"

    def test_missing_chain_configuration_is_a_configuration_error(self, settings, record_path, monkeypatch):
        import src.pipeline as pipeline

        def build(*a, **k):
            raise ConfigError("RPC_URL is missing")

        monkeypatch.setattr(pipeline, "build_chain_client", build)
        with pytest.raises(ConfigError):
            verify(settings, record_path)

    def test_unknown_record_is_not_anchored(self, settings, record_path, monkeypatch):
        client = FakeClient(None, lookup=ChainRecord(exists=False))
        code, report = verify(settings, record_path, client, monkeypatch)
        assert code == 3 and report["checks"]["chain_anchor"]["status"] == "fail"
        assert report["checks"]["url_commitment"]["status"] == "skipped"

    def test_a_record_without_matched_url_cannot_pass_the_commitment_check(self, settings, record_path, monkeypatch):
        record = load_record(record_path)
        record["payload"]["match"].pop("matched_url")
        resealed = seal(record["payload"])
        path = save_record(resealed, record_path.with_name("nourl.json"))
        code, report = verify(settings, path, FakeClient(None), monkeypatch)
        assert code == 4 and report["checks"]["url_commitment"]["status"] == "fail"

    def test_the_commitment_check_is_never_skipped_after_a_pass_on_anchor(self, settings, record_path, monkeypatch):
        calls = []

        class Spy(FakeClient):
            def matches_url(self, data_hash, url):
                calls.append(url)
                return True

        code, _ = verify(settings, record_path, Spy(None), monkeypatch)
        assert code == 0 and calls == [load_record(record_path)["payload"]["match"]["matched_url"]]


class TestLocalTamperPaths:
    def test_edited_record_with_old_digest_fails_integrity(self, settings, record_path):
        record = load_record(record_path)
        mutate_payload(record, "match.matched_url", "https://x.com/attacker/status/1")
        path = save_record(record, record_path.with_name("edited.json"))
        code, report = verify(settings, path)
        assert code == 2 and report["checks"]["local_integrity"]["status"] == "fail"
        assert report["checks"]["chain_anchor"]["status"] == "skipped"  # never reached

    def test_resealed_record_fails_the_anchor_check(self, settings, record_path):
        record = load_record(record_path)
        mutate_payload(record, "match.matched_url", "https://x.com/attacker/status/1")
        path = save_record(seal(record["payload"]), record_path.with_name("resealed.json"))
        code, report = verify(settings, path, dry_run=True)
        assert code == 3
        assert report["checks"]["local_integrity"]["status"] == "pass"
        assert report["checks"]["chain_anchor"]["status"] == "fail"

    def test_altered_url_commitment_on_chain_state_is_caught(self, settings, record_path):
        state_path = settings.root / "localchain.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for entry in state["records"].values():
            entry["url_hash"] = "0x" + "ee" * 32
        state_path.write_text(json.dumps(state), encoding="utf-8")
        code, report = verify(settings, record_path, dry_run=True)
        assert code == 4 and report["checks"]["url_commitment"]["status"] == "fail"

    def test_image_binding_failure_is_reported(self, settings, scene, record_path):
        code, report = verify(settings, record_path, image_path=scene["other"], dry_run=True)
        assert code == 2 and report["checks"]["image_binding"]["status"] == "fail"


class TestSimulationIsLabelled:
    def test_simulated_chain_is_unmistakable(self, settings, record_path, capsys):
        code, report = verify(settings, record_path, dry_run=True)
        out = capsys.readouterr().out
        assert code == 0 and report["simulated"] is True
        assert "SIMULATED" in out and "NOT a" in out and "blockchain" in out
        assert load_record(record_path)["anchor"]["simulated"] is True
        assert load_record(record_path)["anchor"]["network"].endswith("-simulated")

    def test_test_only_records_are_labelled_on_verify(self, settings, record_path, capsys):
        _, report = verify(settings, record_path, dry_run=True)
        assert report["test_only"] is True
        assert "TEST-ONLY" in capsys.readouterr().out


class TestAlgorithmHandling:
    def test_new_records_declare_the_restricted_algorithm(self, record_path):
        assert load_record(record_path)["integrity"]["algorithm"] == INTEGRITY_ALGORITHM
        assert INTEGRITY_ALGORITHM == "sha256-jcs-rfc8785-restricted-v1"

    def test_a_historical_v1_record_still_verifies_under_its_own_rules(self, settings, monkeypatch, tmp_path):
        """A record sealed by the previous build (legacy label, schema v1)."""
        from src.evidence.hashing import canonicalize, digest_hex

        payload = {
            "schema": "faceverify/v1",
            "created_at": "2025-01-01T00:00:00Z",
            "match": {"matched_url": "https://x.com/a/status/1", "big": 2**60},
            "source_image": {"sha256": "0" * 64},
        }
        record = {
            "schema": "faceverify/v1",
            "payload": payload,
            "anchor": None,
            "integrity": {
                "algorithm": "sha256-jcs-rfc8785",
                "verification_hash": digest_hex(payload, legacy=True),
                "canonical_length": len(canonicalize(payload, legacy=True)),
            },
        }
        assert check_local_integrity(record).ok
        # The same payload cannot be sealed under the NEW restricted algorithm...
        from src.evidence.hashing import CanonicalizationError

        with pytest.raises(CanonicalizationError):
            seal(payload)
        # ...and relabelling the historical record does not make it verify.
        record["integrity"]["algorithm"] = INTEGRITY_ALGORITHM
        assert not check_local_integrity(record).ok

    def test_unsupported_algorithm_fails_verification(self, settings, record_path):
        record = load_record(record_path)
        record["integrity"]["algorithm"] = "sha256-made-up"
        path = save_record(record, record_path.with_name("alg.json"))
        code, report = verify(settings, path)
        assert code == 2 and "unsupported integrity algorithm" in report["checks"]["local_integrity"]["detail"]


class TestCliJson:
    def test_json_output_is_machine_readable_and_matches_the_exit_code(self, settings, record_path, capsys, tmp_path):
        env = tmp_path / "empty.env"
        env.write_text("", encoding="utf-8")
        code = main(["verify", "--record", str(record_path), "--dry-run", "--json", "--ascii", "--env", str(env)])
        # settings fixture root differs from the CLI's default root, so the
        # simulated chain is empty: the record is (correctly) not anchored.
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["exit_code"] == code
        assert data["verdict"] in {"verified", "not_anchored"}
        assert set(data["checks"]) == {
            "local_integrity",
            "image_binding",
            "evidence_bundle",
            "chain_anchor",
            "url_commitment",
        }
        assert "VERIFY" in captured.err  # human output went to stderr

    def test_malformed_record_exits_1_with_a_message(self, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        code = main(["verify", "--record", str(bad), "--dry-run", "--ascii"])
        assert code == 1
        assert "RecordError" in capsys.readouterr().err
