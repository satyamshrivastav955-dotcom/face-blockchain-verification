"""
Canonicalization tests.

This is the component whose failure mode is worst: if canonicalization is not
byte-stable, a genuine record reports as tampered, intermittently, on someone
else's machine. So it is pinned down harder than anything else here - including
one exact expected byte string, which is the only kind of assertion that
actually catches a drifting serializer.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.canonical import (
    CanonicalizationError,
    canonicalize,
    digest_hex,
    fmt_score,
    sha256_bytes,
)


class TestExactBytes:
    def test_known_output(self):
        """Pinned byte-for-byte. Any change to the serializer breaks this."""
        obj = {"b": 1, "a": [1, 2, {"z": True, "y": None}], "c": "x"}
        assert canonicalize(obj) == b'{"a":[1,2,{"y":null,"z":true}],"b":1,"c":"x"}'

    def test_no_insignificant_whitespace(self):
        assert b" " not in canonicalize({"a": 1, "b": [1, 2]})

    def test_empty_containers(self):
        assert canonicalize({}) == b"{}"
        assert canonicalize([]) == b"[]"
        assert canonicalize({"a": {}, "b": []}) == b'{"a":{},"b":[]}'

    def test_scalars_at_top_level(self):
        assert canonicalize(None) == b"null"
        assert canonicalize(True) == b"true"
        assert canonicalize(False) == b"false"
        assert canonicalize(0) == b"0"
        assert canonicalize(-17) == b"-17"
        assert canonicalize("hi") == b'"hi"'


class TestOrdering:
    def test_key_order_does_not_affect_output(self):
        a = {"alpha": 1, "beta": 2, "gamma": 3}
        b = {"gamma": 3, "alpha": 1, "beta": 2}
        assert canonicalize(a) == canonicalize(b)
        assert digest_hex(a) == digest_hex(b)

    def test_nested_key_order_does_not_matter(self):
        a = {"outer": {"x": 1, "y": {"p": 1, "q": 2}}}
        b = {"outer": {"y": {"q": 2, "p": 1}, "x": 1}}
        assert canonicalize(a) == canonicalize(b)

    def test_array_order_is_significant(self):
        assert canonicalize([1, 2]) != canonicalize([2, 1])

    def test_utf16_code_unit_ordering(self):
        """RFC 8785 orders keys by UTF-16 code unit, not code point.

        U+10000 encodes as the surrogate pair D800 DC00, so it must sort
        *before* U+E000 - the opposite of Python's default string sort. Getting
        this wrong would only ever show up against another JCS implementation.
        """
        obj = {"\ue000": 1, "\U00010000": 2}
        out = canonicalize(obj).decode("utf-8")
        assert out.index("\U00010000") < out.index("\ue000")
        assert sorted(obj) == ["\ue000", "\U00010000"]  # Python disagrees


class TestFloatRejection:
    def test_top_level_float_rejected(self):
        with pytest.raises(CanonicalizationError):
            canonicalize(0.1)

    def test_nested_float_reports_its_path(self):
        with pytest.raises(CanonicalizationError) as excinfo:
            canonicalize({"match": {"scores": [1, 0.9]}})
        assert "match.scores[1]" in str(excinfo.value)

    def test_decimal_rejected(self):
        with pytest.raises(CanonicalizationError):
            canonicalize({"x": Decimal("1.5")})

    def test_unsupported_type_rejected(self):
        with pytest.raises(CanonicalizationError):
            canonicalize({"when": object()})

    def test_non_string_key_rejected(self):
        with pytest.raises(CanonicalizationError):
            canonicalize({1: "one"})


class TestBooleansAreNotIntegers:
    def test_true_is_not_one(self):
        # isinstance(True, int) is True in Python; the writer must check bool first.
        assert canonicalize({"a": True}) == b'{"a":true}'
        assert canonicalize({"a": 1}) == b'{"a":1}'
        assert digest_hex({"a": True}) != digest_hex({"a": 1})


class TestUnicode:
    def test_emitted_literally_not_escaped(self):
        out = canonicalize({"title": "café ☕"})
        assert "café ☕".encode("utf-8") in out
        assert b"\\u" not in out

    def test_control_characters_are_escaped(self):
        assert canonicalize({"a": "x\ny"}) == b'{"a":"x\\ny"}'
        assert canonicalize({"a": "\u0001"}) == b'{"a":"\\u0001"}'

    def test_quotes_and_backslashes(self):
        assert canonicalize({"a": 'he said "hi"'}) == b'{"a":"he said \\"hi\\""}'
        assert canonicalize({"a": "c:\\temp"}) == b'{"a":"c:\\\\temp"}'


class TestStability:
    def test_round_trip_through_json_is_stable(self):
        """A record is written to disk and re-read before verification.

        The hash therefore has to survive a json.dumps/json.loads round trip -
        if it did not, every verify of a genuine record would fail.
        """
        payload = {
            "created_at": "2026-09-03T10:00:00Z",
            "match": {"url": "https://x.com/a/status/1", "score": "0.7412"},
            "counts": {"faces": 2, "candidates": 17},
            "flags": {"social": True, "stub": False, "note": None},
        }
        before = digest_hex(payload)
        reloaded = json.loads(json.dumps(payload, indent=2, ensure_ascii=False))
        assert digest_hex(reloaded) == before

    def test_digest_hex_prefix(self):
        assert digest_hex({"a": 1}).startswith("0x")
        assert len(digest_hex({"a": 1})) == 66
        assert not digest_hex({"a": 1}, prefix=False).startswith("0x")

    def test_digest_matches_manual_sha256(self):
        import hashlib

        obj = {"a": 1}
        expected = hashlib.sha256(b'{"a":1}').hexdigest()
        assert digest_hex(obj, prefix=False) == expected
        assert sha256_bytes(b'{"a":1}') == expected


class TestFmtScore:
    def test_fixed_precision(self):
        assert fmt_score(0.5) == "0.5000"
        assert fmt_score(0.36349999) == "0.3635"
        assert fmt_score(1) == "1.0000"
        assert fmt_score(-0.0) == "-0.0000" or fmt_score(-0.0) == "0.0000"

    def test_output_is_canonicalizable(self):
        # The whole point: a score becomes a string so it can enter the payload.
        canonicalize({"score": fmt_score(0.87654321)})

    def test_nan_and_infinity_rejected(self):
        with pytest.raises(CanonicalizationError):
            fmt_score(float("nan"))
        with pytest.raises(CanonicalizationError):
            fmt_score(float("inf"))

    def test_precision_is_configurable(self):
        assert fmt_score(0.123456, places=2) == "0.12"
        assert fmt_score(0.123456, places=6) == "0.123456"
