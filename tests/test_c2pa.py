"""
C2PA Content Credentials reading: summary logic, failure handling, and the record fields.

The summary logic is tested with hand-built manifest stores. A real signed sample (the
c2pa-rs ``CA.jpg`` test fixture, signed with a *test* certificate) is used when it has been
downloaded to ``eval_data/c2pa/CA.jpg``; those tests are skipped otherwise.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.evidence.hashing import canonicalize
from src.verification.c2pa_check import (
    ContentCredentials,
    inspect_content_credentials,
    summarise_manifest_store,
)

SAMPLE = Path(__file__).resolve().parent.parent / "eval_data" / "c2pa" / "CA.jpg"


def store(state="Valid", status=None, actions=None, source=None, ingredients=0):
    action_list = [{"action": a} for a in (actions or [])]
    if source:
        action_list.append({"action": "c2pa.created", "digitalSourceType": source})
    return {
        "active_manifest": "m1",
        "validation_state": state,
        "validation_status": [{"code": c} for c in (status or [])],
        "manifests": {
            "m1": {
                "claim_generator_info": [{"name": "SomeTool", "version": "1"}],
                "signature_info": {
                    "alg": "Es256",
                    "issuer": "Acme CA",
                    "common_name": "Acme Signer",
                    "time": "2026-01-01T00:00:00+00:00",
                },
                "assertions": [{"label": "c2pa.actions.v2", "data": {"actions": action_list}}],
                "ingredients": [{}] * ingredients,
            }
        },
    }


class TestSummary:
    def test_valid_manifest(self):
        cc = summarise_manifest_store(store(actions=["c2pa.opened", "c2pa.cropped"], ingredients=2))
        assert cc.state == "valid" and not cc.untrusted_signer and not cc.ai_generated
        assert cc.issuer == "Acme CA" and cc.claim_generator == "SomeTool"
        assert cc.actions == ["c2pa.opened", "c2pa.cropped"] and cc.ingredients == 2

    def test_untrusted_signer_is_flagged_but_not_invalid(self):
        cc = summarise_manifest_store(store(status=["signingCredential.untrusted"]))
        assert cc.state == "valid" and cc.untrusted_signer

    def test_a_hash_mismatch_is_invalid(self):
        cc = summarise_manifest_store(store(status=["assertion.hashedURI.mismatch"]))
        assert cc.state == "invalid"
        assert summarise_manifest_store(store(state="Invalid")).state == "invalid"

    def test_ai_generation_is_reported_only_from_the_manifests_own_declaration(self):
        ai = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
        assert summarise_manifest_store(store(source=ai)).ai_generated is True
        cam = "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture"
        assert summarise_manifest_store(store(source=cam)).ai_generated is False
        assert summarise_manifest_store(store()).ai_generated is False

    @pytest.mark.parametrize(
        "bad",
        [
            {},
            {"active_manifest": None},
            {"active_manifest": "x", "manifests": {}},
            {"active_manifest": "x", "manifests": {"x": "not a dict"}},
        ],
    )
    def test_no_active_manifest_is_absent(self, bad):
        assert summarise_manifest_store(bad).state == "absent"

    def test_summary_is_hash_safe(self):
        out = summarise_manifest_store(store(actions=["a"], status=["signingCredential.untrusted"])).to_json()
        canonicalize(out)  # strings, ints and bools only: no floats
        assert json.loads(json.dumps(out)) == out

    def test_output_is_bounded(self):
        cc = ContentCredentials(actions=[str(i) for i in range(500)], issuer="x" * 1000, failure_codes=["c"] * 500)
        out = cc.to_json()
        assert len(out["actions"]) <= 20 and len(out["issuer"]) <= 120 and len(out["failure_codes"]) <= 20


def jpeg_bytes():
    ok, buf = cv2.imencode(".jpg", np.full((64, 64, 3), 90, np.uint8))
    assert ok
    return buf.tobytes()


class TestInspect:
    def test_plain_image_has_no_credentials(self):
        assert inspect_content_credentials(jpeg_bytes()).state == "absent"

    def test_unsupported_and_garbage_input_never_raise(self):
        assert inspect_content_credentials(b"definitely not an image").state == "unsupported_format"
        assert inspect_content_credentials(b"").state == "unsupported_format"
        assert inspect_content_credentials(b"\xff\xd8\xff" + b"\x00" * 50).state in ("absent", "error")

    def test_missing_library_is_reported_not_raised(self, monkeypatch):
        real = builtins.__import__

        def fake(name, *a, **k):
            if name == "c2pa":
                raise ImportError("no c2pa")
            return real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake)
        assert inspect_content_credentials(jpeg_bytes()).state == "unavailable"


@pytest.mark.skipif(not SAMPLE.is_file(), reason="sample not downloaded (eval_data/c2pa/CA.jpg)")
class TestRealSignedSample:
    def test_valid_but_untrusted_test_certificate(self):
        cc = inspect_content_credentials(SAMPLE.read_bytes())
        assert cc.state == "valid" and cc.untrusted_signer
        assert cc.issuer == "C2PA Test Signing Cert" and "c2pa.opened" in cc.actions

    def test_tampering_with_the_pixels_invalidates_it(self):
        raw = bytearray(SAMPLE.read_bytes())
        raw[60000] ^= 0xFF
        cc = inspect_content_credentials(bytes(raw))
        assert cc.state == "invalid" and any("mismatch" in c for c in cc.failure_codes)

    def test_pipeline_records_content_credentials_for_the_source_image(self, settings, tmp_path):
        from src.pipeline import run_register
        from src.ui import Console

        query = tmp_path / "signed.jpg"
        query.write_bytes(SAMPLE.read_bytes())
        fixture = tmp_path / "fx.json"
        fixture.write_text(json.dumps({"candidates": []}), encoding="utf-8")
        settings.fixture_path = str(fixture)
        run_register(
            settings,
            query,
            provider_name="local_fixture",
            engine_name="stub",
            dry_run=True,
            allow_offline_stub=True,
            console=Console(force_ascii=True),
        )
        # no candidates -> no record; the credentials still appear in the evidence log
        assert not (settings.output_dir / "verification.json").exists()


def test_new_records_carry_the_credentials_summary(settings, scene):
    from src.evidence.record import load_record
    from src.pipeline import run_register
    from src.ui import Console

    settings.fixture_path = str(scene["fixture"])
    assert (
        run_register(
            settings,
            scene["query"],
            provider_name="local_fixture",
            engine_name="stub",
            dry_run=True,
            allow_offline_stub=True,
            console=Console(force_ascii=True),
        )
        == 0
    )
    payload = load_record(settings.output_dir / "verification.json")["payload"]
    assert payload["source_image"]["content_credentials"]["state"] in ("absent", "unavailable")
    assert payload["match"]["candidate_content_credentials"]["state"] in ("absent", "unavailable")
