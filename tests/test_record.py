"""
Record sealing, tamper detection, and the two forgery classes.

These tests encode the security claim the whole project rests on: an edited
record is detectable, and *how* it is detectable depends on how carefully it
was edited.
"""

from __future__ import annotations

import json

import pytest

from src.canonical import digest_hex
from src.record import (
    INTEGRITY_ALGORITHM,
    Status,
    attach_anchor,
    build_payload,
    check_local_integrity,
    load_record,
    mutate_payload,
    save_record,
    seal,
    utc_now,
)


def sample_payload() -> dict:
    return build_payload(
        source_image={
            "filename": "query.png",
            "sha256": "a" * 64,
            "bytes": 12345,
            "width": 256,
            "height": 256,
            "phash": "0123456789abcdef",
        },
        face={
            "engine": "opencv-yunet+sface",
            "models": {"detector": "yunet.onnx", "recognizer": "sface.onnx"},
            "face_count": 1,
            "encodable_face_count": 1,
            "primary": {"bbox": {"x": 10, "y": 12, "w": 80, "h": 96}, "landmarks": []},
            "primary_det_score": "0.9912",
            "embedding_dim": 128,
            "embedding_sha256": "b" * 64,
            "embedding_on_chain": False,
        },
        search={
            "provider": "serpapi_lens",
            "endpoint": "https://serpapi.com/search",
            "searched_at": "2026-09-03T10:00:00Z",
            "query_image_url": "https://files.example/q.png",
            "raw_response_sha256": "c" * 64,
            "candidates_returned": 12,
            "candidates_confirmed": 12,
            "candidates_sha256": "d" * 64,
            "offline_stub": False,
        },
        match={
            "matched_url": "https://x.com/realuser/status/1234567890",
            "matched_domain": "x.com",
            "matched_image_url": "https://pbs.example/media/abc.jpg",
            "matched_image_sha256": "e" * 64,
            "matched_image_phash": "0123456789abcdef",
            "is_social_media": True,
            "decision_rule": "confirmed_face_match",
            "face_similarity": "0.7412",
            "face_cosine_threshold": "0.3630",
            "phash_distance": 6,
            "phash_max_distance": 12,
            "faces_in_matched_image": 1,
            "provider_position": 2,
            "claim": "image provenance, not identity",
        },
        created_at="2026-09-03T10:00:00Z",
    )


class TestSeal:
    def test_envelope_shape(self):
        record = seal(sample_payload())
        assert set(record) == {"schema", "payload", "integrity", "anchor"}
        assert record["anchor"] is None
        assert record["integrity"]["algorithm"] == INTEGRITY_ALGORITHM

    def test_hash_covers_only_the_payload(self):
        payload = sample_payload()
        record = seal(payload)
        assert record["integrity"]["verification_hash"] == digest_hex(payload)

    def test_canonical_length_recorded(self):
        record = seal(sample_payload())
        assert record["integrity"]["canonical_length"] > 100

    def test_payload_is_canonicalizable(self):
        # A float anywhere in the payload would raise here - the guard that
        # keeps scores stored as fixed-precision strings honest.
        seal(sample_payload())


class TestAnchorIsOutsideTheHash:
    def test_attaching_an_anchor_does_not_change_the_hash(self):
        """The tx id does not exist until after the hash is computed.

        If attaching it changed the hash, every record would be born invalid.
        """
        record = seal(sample_payload())
        before = record["integrity"]["verification_hash"]
        attach_anchor(record, {"tx_hash": "0x" + "ab" * 32, "block_number": 42})
        assert check_local_integrity(record).ok
        assert record["integrity"]["verification_hash"] == before

    def test_editing_the_anchor_does_not_break_local_integrity(self):
        # Deliberate: the anchor is a *claim about* the record, and it is the
        # chain lookup - not the local hash - that adjudicates it.
        record = seal(sample_payload())
        attach_anchor(record, {"tx_hash": "0x" + "ab" * 32})
        record["anchor"]["tx_hash"] = "0x" + "ff" * 32
        assert check_local_integrity(record).ok


class TestNaiveTampering:
    """Forgery class 1: edit the payload, leave the hash alone."""

    @pytest.mark.parametrize(
        "field,value",
        [
            ("match.matched_url", "https://instagram.com/p/ATTACKER/"),
            ("match.face_similarity", "0.9999"),
            ("match.is_social_media", False),
            ("match.phash_distance", 0),
            ("source_image.sha256", "f" * 64),
            ("face.embedding_sha256", "0" * 64),
            ("search.provider", "totally_made_up"),
            ("created_at", "1999-01-01T00:00:00Z"),
        ],
    )
    def test_every_payload_field_is_covered_by_the_hash(self, field, value):
        record = seal(sample_payload())
        mutate_payload(record, field, value)
        check = check_local_integrity(record)
        assert not check.ok
        assert check.stored_hash != check.recomputed_hash

    def test_reordering_keys_is_not_tampering(self):
        record = seal(sample_payload())
        record["payload"] = dict(reversed(list(record["payload"].items())))
        assert check_local_integrity(record).ok

    def test_status_exit_code(self):
        assert Status.LOCAL_HASH_MISMATCH.exit_code == 2


class TestResealedTampering:
    """Forgery class 2: edit the payload *and* recompute the hash."""

    def test_reseal_passes_local_checks(self):
        record = seal(sample_payload())
        genuine = record["integrity"]["verification_hash"]

        mutate_payload(record, "match.matched_url", "https://x.com/attacker/status/1")
        forged = seal(record["payload"])

        # Internally flawless - nothing offline can fault it...
        assert check_local_integrity(forged).ok
        # ...but it is a different commitment, and only the original was anchored.
        assert forged["integrity"]["verification_hash"] != genuine

    def test_only_the_chain_can_catch_it(self):
        """Documents why the blockchain is load-bearing rather than decorative."""
        record = seal(sample_payload())
        anchored_hash = record["integrity"]["verification_hash"]

        mutate_payload(record, "match.face_similarity", "0.9999")
        forged = seal(record["payload"])
        forged["anchor"] = {"tx_hash": "0x" + "ab" * 32}  # the old, real tx

        assert check_local_integrity(forged).ok
        registry = {anchored_hash}
        assert forged["integrity"]["verification_hash"] not in registry


class TestMutatePayload:
    def test_returns_the_old_value(self):
        record = seal(sample_payload())
        old = mutate_payload(record, "match.matched_url", "https://example.com/")
        assert old == "https://x.com/realuser/status/1234567890"

    def test_unknown_field_raises(self):
        record = seal(sample_payload())
        with pytest.raises(KeyError):
            mutate_payload(record, "match.does_not_exist", "x")
        with pytest.raises(KeyError):
            mutate_payload(record, "nope.nested.deep", "x")

    def test_cannot_walk_through_a_scalar(self):
        record = seal(sample_payload())
        with pytest.raises(KeyError):
            mutate_payload(record, "match.matched_url.sub", "x")


class TestPersistence:
    def test_round_trip(self, tmp_path):
        record = seal(sample_payload())
        attach_anchor(record, {"tx_hash": "0x" + "cd" * 32, "block_number": 7})
        path = save_record(record, tmp_path / "out" / "verification.json")
        assert path.exists()

        reloaded = load_record(path)
        assert reloaded == record
        assert check_local_integrity(reloaded).ok

    def test_indentation_does_not_affect_the_hash(self, tmp_path):
        record = seal(sample_payload())
        path = tmp_path / "compact.json"
        path.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
        assert check_local_integrity(load_record(path)).ok

    def test_unicode_survives_the_file(self, tmp_path):
        payload = sample_payload()
        payload["match"]["matched_url"] = "https://x.com/user/status/1?q=café☕"
        record = seal(payload)
        path = save_record(record, tmp_path / "v.json")
        assert check_local_integrity(load_record(path)).ok

    def test_missing_keys_rejected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"payload": {}}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_record(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_record(tmp_path / "nope.json")


class TestNotes:
    def test_algorithm_change_is_noted(self):
        record = seal(sample_payload())
        record["integrity"]["algorithm"] = "sha256-someone-elses-scheme"
        check = check_local_integrity(record)
        assert check.ok  # the bytes still agree...
        assert any("algorithm" in note for note in check.notes)  # ...but flag it

    def test_canonical_length_change_is_noted(self):
        record = seal(sample_payload())
        mutate_payload(record, "match.matched_url", "https://x.com/a/status/999999999999")
        check = check_local_integrity(record)
        assert not check.ok
        assert any("canonical length" in note for note in check.notes)


def test_utc_now_is_fixed_width():
    stamp = utc_now()
    assert len(stamp) == 20
    assert stamp.endswith("Z")
    assert "." not in stamp  # no microseconds: they would destabilise nothing,
    # but fixed width keeps the record legible and the format unambiguous
