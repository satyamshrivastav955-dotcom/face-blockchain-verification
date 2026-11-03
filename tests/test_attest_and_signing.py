"""Signing, image-only attestation, and the verify paths that use them (all offline)."""

from __future__ import annotations

import copy
import json

import cv2
import pytest

from src.attest import build_attestation_payload, run_attest
from src.evidence.record import load_record, save_record, seal
from src.main import main
from src.pipeline import run_verify
from src.signals import extract_synthetic_signals
from src.trust import (
    SigningError,
    check_signature,
    generate_key,
    load_private_key,
    sign_record,
)
from src.ui import Console
from conftest import make_blob


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "photo.png"
    cv2.imwrite(str(path), make_blob())
    return path


@pytest.fixture
def key_path(tmp_path):
    path = tmp_path / "k.pem"
    generate_key(path)
    return path


def _verify(settings, record_path, **kw):
    report: dict = {}
    code = run_verify(settings, record_path, console=Console(force_ascii=True), report=report, **kw)
    return code, report


class TestSigning:
    def test_roundtrip_and_pinning(self, tmp_path, key_path):
        key = load_private_key(key_path)
        record = sign_record(seal({"schema": "faceproof/attestation/v1", "a": 1}), key)
        h = record["integrity"]["verification_hash"]
        pub = record["signature"]["public_key"]
        assert check_signature(record, h).state == "valid"
        assert check_signature(record, h).pinned is None
        assert check_signature(record, h, [pub]).pinned is True

    def test_other_key_is_not_pinned(self, tmp_path, key_path):
        other = tmp_path / "o.pem"
        other_pub = generate_key(other)
        record = sign_record(seal({"schema": "faceproof/attestation/v1"}), load_private_key(key_path))
        res = check_signature(record, record["integrity"]["verification_hash"], [other_pub])
        assert res.state == "valid" and res.pinned is False and not res.ok

    def test_unsigned_fails_when_a_key_is_required(self):
        record = seal({"schema": "faceproof/attestation/v1"})
        h = record["integrity"]["verification_hash"]
        assert check_signature(record, h).ok
        assert not check_signature(record, h, ["00" * 32]).ok

    def test_signature_bound_to_the_hash_not_the_stored_field(self, key_path):
        record = sign_record(seal({"schema": "faceproof/attestation/v1", "n": 1}), load_private_key(key_path))
        forged = seal({"schema": "faceproof/attestation/v1", "n": 2})
        forged["signature"] = copy.deepcopy(record["signature"])
        assert check_signature(forged, forged["integrity"]["verification_hash"]).state == "invalid"

    def test_corrupted_signature_is_invalid(self, key_path):
        record = sign_record(seal({"schema": "faceproof/attestation/v1"}), load_private_key(key_path))
        sig = record["signature"]["signature"]
        record["signature"]["signature"] = ("0" if sig[0] != "0" else "1") + sig[1:]
        assert check_signature(record, record["integrity"]["verification_hash"]).state == "invalid"

    def test_keygen_never_overwrites(self, key_path):
        with pytest.raises(SigningError):
            generate_key(key_path)

    def test_garbage_key_file_is_a_clear_error(self, tmp_path):
        bad = tmp_path / "bad.pem"
        bad.write_text("not a key")
        with pytest.raises(SigningError):
            load_private_key(bad)


class TestAttest:
    def test_payload_has_no_face_data_and_no_filename(self, image):
        payload = build_attestation_payload(image)
        text = json.dumps(payload)
        assert "embedding" not in text and "face" not in payload
        assert "photo.png" not in text
        assert payload["source_image"]["sha256"] and len(payload["source_image"]["phash"]) == 16
        assert payload["synthetic_media_signals"]["is_detector"] is False

    def test_attest_then_verify_requires_an_anchor(self, settings, image, key_path, tmp_path):
        settings.signing_key_file = str(key_path)
        out = tmp_path / "att.json"
        assert run_attest(settings, image, sign=True, output=out, console=Console(force_ascii=True)) == 0
        code, report = _verify(settings, out, image_path=image)
        assert code == 3  # sealed and signed, but no time evidence: fails closed
        assert report["checks"]["signature"]["status"] == "pass"
        assert report["checks"]["image_binding"]["status"] == "pass"
        assert report["checks"]["chain_anchor"]["status"] == "fail"

    def test_wrong_image_is_rejected(self, settings, image, tmp_path):
        out = tmp_path / "att.json"
        run_attest(settings, image, output=out, console=Console(force_ascii=True))
        other = tmp_path / "other.png"
        cv2.imwrite(str(other), make_blob(cx=0.7))
        code, report = _verify(settings, out, image_path=other)
        assert code == 2 and report["checks"]["image_binding"]["status"] == "fail"

    def test_edited_payload_is_rejected_even_when_resealed_and_signed_by_the_old_key(
        self, settings, image, key_path, tmp_path
    ):
        settings.signing_key_file = str(key_path)
        out = tmp_path / "att.json"
        run_attest(settings, image, sign=True, output=out, console=Console(force_ascii=True))
        genuine = load_record(out)
        forged_payload = copy.deepcopy(genuine["payload"])
        forged_payload["source_image"]["sha256"] = "0" * 64
        forged = seal(forged_payload)
        forged["signature"] = genuine["signature"]  # the forger can only copy the old signature
        path = save_record(forged, tmp_path / "forged.json")
        code, report = _verify(settings, path)
        assert code == 2 and report["checks"]["signature"]["status"] == "fail"

    def test_pinning_the_wrong_key_fails(self, settings, image, key_path, tmp_path):
        settings.signing_key_file = str(key_path)
        out = tmp_path / "att.json"
        run_attest(settings, image, sign=True, output=out, console=Console(force_ascii=True))
        code, report = _verify(settings, out, trusted_keys=["11" * 32])
        assert code == 2 and "not in the trusted set" in report["checks"]["signature"]["detail"]

    def test_require_image_is_inconclusive_without_one(self, settings, image, tmp_path):
        out = tmp_path / "att.json"
        run_attest(settings, image, output=out, console=Console(force_ascii=True))
        code, _ = _verify(settings, out, require_image=True)
        assert code == 6

    def test_ots_needs_explicit_consent_and_sends_nothing(self, settings, image, tmp_path, monkeypatch):
        import src.anchors.ots as ots

        monkeypatch.setattr(ots, "submit_digest", lambda *a, **k: pytest.fail("network call without consent"))
        out = tmp_path / "att.json"
        code = run_attest(settings, image, anchor_backend="ots", output=out, console=Console(force_ascii=True))
        assert code == 1 and not out.exists()

    def test_ots_pending_is_not_success_and_confirmed_is(self, settings, image, tmp_path, monkeypatch):
        import hashlib

        from bitcoin.core import CBlockHeader
        from opentimestamps.core import notary, op
        from opentimestamps.core.timestamp import Timestamp

        import src.anchors.ots as ots

        class Cal:
            confirmed: dict = {}

            def __init__(self, url):
                self.url = url

            def submit(self, digest, timeout=None):
                ts = Timestamp(digest)
                ts.ops.add(op.OpSHA256()).attestations.add(notary.PendingAttestation(self.url))
                return ts

            def get_timestamp(self, commitment, timeout=None):
                if commitment not in self.confirmed:
                    raise KeyError
                ts = Timestamp(commitment)
                ts.attestations.add(notary.BitcoinBlockHeaderAttestation(900_000))
                return ts

        real_submit = ots.submit_digest
        monkeypatch.setattr(
            ots, "submit_digest", lambda h, c=ots.DEFAULT_CALENDARS: real_submit(h, c, calendar_factory=Cal)
        )
        monkeypatch.setattr("src.anchors.submit_digest", ots.submit_digest)
        out = tmp_path / "att.json"
        assert (
            run_attest(
                settings,
                image,
                anchor_backend="ots",
                consent_timestamp_calendars=True,
                output=out,
                console=Console(force_ascii=True),
            )
            == 0
        )
        record = load_record(out)
        assert record["anchor"]["status"] == "pending"
        code, report = _verify(settings, out, image_path=image)
        assert code == 3 and report["anchor_mode"] == "opentimestamps"

        vhash = record["integrity"]["verification_hash"]
        commitment = hashlib.sha256(bytes.fromhex(vhash[2:])).digest()
        Cal.confirmed[commitment] = True
        upgraded, n = ots.upgrade_anchor(record["anchor"], calendar_factory=Cal)
        assert n >= 1  # one per calendar that holds the commitment
        record["anchor"] = upgraded
        save_record(record, out)
        header = CBlockHeader(
            nVersion=4, hashPrevBlock=b"\x00" * 32, hashMerkleRoot=commitment, nTime=1_700_000_000, nBits=0x1D00FFFF
        ).serialize()
        code, report = _verify(settings, out, image_path=image, ots_header_fetcher=lambda h: header)
        assert code == 0 and report["ots"]["block_height"] == 900_000 and report["bound_to_image"] is True

        # explorers down -> inconclusive, never a pass
        def down(h):
            raise ots.OtsError("no block explorer answered")

        code, _ = _verify(settings, out, image_path=image, ots_header_fetcher=down)
        assert code == 6


class TestCli:
    def test_keygen_attest_verify_roundtrip(self, tmp_path, image, capsys):
        env = tmp_path / "e.env"
        env.write_text("", encoding="utf-8")
        key = tmp_path / "cli.pem"
        assert main(["keygen", "--out", str(key), "--ascii", "--env", str(env)]) == 0
        pub = next(line for line in capsys.readouterr().out.splitlines() if "public key" in line).split()[-1]
        out = tmp_path / "a.json"
        monkey_env = {"SIGNING_KEY_FILE": str(key)}
        import os

        os.environ.update(monkey_env)
        try:
            assert (
                main(["attest", "--image", str(image), "--sign", "--output", str(out), "--ascii", "--env", str(env)])
                == 0
            )
            capsys.readouterr()
            code = main(
                [
                    "verify",
                    "--record",
                    str(out),
                    "--image",
                    str(image),
                    "--trusted-key",
                    pub,
                    "--json",
                    "--ascii",
                    "--env",
                    str(env),
                ]
            )
        finally:
            os.environ.pop("SIGNING_KEY_FILE", None)
        data = json.loads(capsys.readouterr().out)
        assert code == 3 and data["checks"]["signature"]["status"] == "pass" and data["signature"]["pinned"] is True


class TestSyntheticSignals:
    def test_plain_image_has_no_declaration(self, image):
        s = extract_synthetic_signals(image.read_bytes())
        assert s.verdict == "no_declaration" and s.to_json()["absence_proves_nothing"] is True

    def test_png_generator_chunk_is_a_declaration(self):
        import struct
        import zlib

        def chunk(t, body):
            return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body))

        png = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"tEXt", b"parameters\x00a cat, Steps: 20, Sampler: Euler")
            + chunk(b"IEND", b"")
        )
        s = extract_synthetic_signals(png)
        assert s.verdict == "declared_synthetic" and s.signals[0]["kind"] == "png_generator_chunk"

    def test_c2pa_flag_and_xmp_source_type(self):
        assert extract_synthetic_signals(b"x", c2pa_ai_generated=True).verdict == "declared_synthetic"
        xmp = (
            b"http://ns.adobe.com/xmp/1.0/\x00<x:xmpmeta Iptc4xmpExt:DigitalSourceType="
            b"'http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia'/>"
        )
        jpeg = b"\xff\xd8\xff\xe1" + (len(xmp) + 2).to_bytes(2, "big") + xmp + b"\xff\xd9"
        s = extract_synthetic_signals(jpeg)
        assert s.verdict == "declared_synthetic" and s.signals[0]["kind"] == "xmp_digital_source_type"


class TestTamperSuite:
    def test_every_forgery_is_rejected_and_the_control_passes(self, image, tmp_path, capsys):
        env = tmp_path / "e.env"
        env.write_text("", encoding="utf-8")
        assert main(["tamper-demo", "--suite", "attestation", "--image", str(image), "--ascii", "--env", str(env)]) == 0
        out = capsys.readouterr().out
        assert out.count("REJECTED") == 6 and "CONTROL" in out and "[X]" not in out

    def test_requires_an_image(self, tmp_path):
        env = tmp_path / "e.env"
        env.write_text("", encoding="utf-8")
        assert main(["tamper-demo", "--suite", "attestation", "--ascii", "--env", str(env)]) == 1
