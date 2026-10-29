"""
Canonicalization against RFC 8785 behaviour, and the honest limits of this profile.

The project's canonicalizer is a *restricted profile* of RFC 8785: byte-identical
to JCS for every value it accepts, but it rejects floats and integers outside
+/-(2**53-1) and ill-formed Unicode. It is therefore labelled
``sha256-jcs-rfc8785-restricted-v1`` and not "RFC 8785 compliant".

Vectors below follow RFC 8785 section 3.2 (sorting, string escaping, literals);
the RFC's float vectors (Appendix B) are intentionally out of profile and are
asserted to be *rejected*.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess

import pytest

from src.evidence.hashing import (
    MAX_DEPTH,
    MAX_SAFE_INTEGER,
    CanonicalizationError,
    canonicalize,
    digest_hex,
)


class TestRfc8785Vectors:
    def test_string_and_literal_example_from_section_3_2_2(self):
        # RFC 8785 section 3.2.2 example, number members removed (out of profile).
        bs = chr(92)
        text = chr(0x20AC) + "$" + chr(0x0F) + chr(0x0A) + "A'B" + chr(34) + bs + bs + chr(34) + "/"
        value = {"string": text, "literals": [None, True, False]}
        expected = (
            '{"literals":[null,true,false],"string":"'
            + chr(0x20AC)
            + "$"
            + bs
            + "u000f"
            + bs
            + "n"
            + "A'B"
            + bs
            + chr(34)
            + bs * 4
            + bs
            + chr(34)
            + '/"}'
        )
        assert canonicalize(value) == expected.encode("utf-8")

    def test_property_sorting_example_from_section_3_2_3(self):
        euro, cr, dalet = chr(0x20AC), chr(0x0D), chr(0xFB33)
        o_uml, emoji, c1 = chr(0xF6), chr(0x1F600), chr(0x80)
        value = {
            euro: "Euro Sign",
            cr: "Carriage Return",
            dalet: "Hebrew Letter Dalet With Dagesh",
            "1": "One",
            emoji: "Emoji: Grinning Face",
            c1: "Control",
            o_uml: "Latin Small Letter O With Diaeresis",
        }
        keys = list(json.loads(canonicalize(value).decode("utf-8")).keys())
        # UTF-16 code-unit order: the emoji (surrogate pair D83D DE00) sorts
        # BEFORE U+FB33, unlike Python's code-point order.
        assert keys == [cr, "1", c1, o_uml, euro, emoji, dalet]
        assert sorted(value) != keys  # Python's default order would be wrong

    def test_recursive_key_ordering_and_array_order_preserved(self):
        value = {"b": {"z": 1, "a": [3, 1, 2]}, "a": {"y": 0, "x": 0}}
        assert canonicalize(value) == b'{"a":{"x":0,"y":0},"b":{"a":[3,1,2],"z":1}}'

    def test_no_insignificant_whitespace(self):
        assert b" " not in canonicalize({"a": [1, 2], "b": {"c": None}})

    def test_control_characters_use_short_or_lowercase_u00xx_escapes(self):
        assert canonicalize("\b\t\n\f\r") == b'"\\b\\t\\n\\f\\r"'
        assert canonicalize("\x00\x1f") == b'"\\u0000\\u001f"'
        assert canonicalize("\x7f") == b'"\x7f"'  # DEL is not escaped
        assert canonicalize('"\\') == b'"\\"\\\\"'
        assert canonicalize("/") == b'"/"'  # solidus is never escaped

    def test_non_ascii_is_emitted_as_utf8_not_escaped(self):
        assert canonicalize("café \U0001f600") == '"café \U0001f600"'.encode("utf-8")

    def test_digest_is_sha256_of_the_canonical_bytes(self):
        obj = {"k": ["v", 1]}
        assert digest_hex(obj) == "0x" + hashlib.sha256(canonicalize(obj)).hexdigest()
        # fixed known value so a regression cannot pass by changing both sides
        assert digest_hex({"a": 1}, prefix=False) == hashlib.sha256(b'{"a":1}').hexdigest()
        assert digest_hex({"a": 1}) == ("0x015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862")


class TestProfileRestrictions:
    @pytest.mark.parametrize("value", [1.5, 0.0, float("nan"), float("inf"), {"x": [1e30]}])
    def test_floats_are_rejected(self, value):
        with pytest.raises(CanonicalizationError):
            canonicalize(value)

    def test_integers_beyond_the_ijson_safe_range_are_rejected(self):
        assert canonicalize(MAX_SAFE_INTEGER) == str(MAX_SAFE_INTEGER).encode()
        assert canonicalize(-MAX_SAFE_INTEGER) == str(-MAX_SAFE_INTEGER).encode()
        for too_big in (MAX_SAFE_INTEGER + 1, -MAX_SAFE_INTEGER - 1, 10**30):
            with pytest.raises(CanonicalizationError):
                canonicalize(too_big)
        # ...but the historical rules (legacy records) accept them.
        assert canonicalize(10**30, legacy=True) == b"1" + b"0" * 30

    def test_lone_surrogates_are_rejected_in_values_and_keys(self):
        for bad in ("\ud800", "x\udfffy"):
            with pytest.raises(CanonicalizationError):
                canonicalize(bad)
            with pytest.raises(CanonicalizationError):
                canonicalize({bad: 1})

    def test_valid_surrogate_pair_as_one_codepoint_is_fine(self):
        assert canonicalize("\U0001f600") == '"\U0001f600"'.encode("utf-8")

    @pytest.mark.parametrize("value", [b"bytes", {1, 2}, object(), {1: "non-string key"}])
    def test_unsupported_types_are_rejected(self, value):
        with pytest.raises(CanonicalizationError):
            canonicalize(value)

    def test_excessive_nesting_is_rejected_not_a_crash(self):
        deep: list = []
        node = deep
        for _ in range(MAX_DEPTH + 5):
            nxt: list = []
            node.append(nxt)
            node = nxt
        with pytest.raises(CanonicalizationError):
            canonicalize(deep)

    def test_bool_is_not_confused_with_int(self):
        assert canonicalize([True, 1, False, 0]) == b"[true,1,false,0]"

    def test_round_trip_is_stable(self):
        value = {"z": [1, {"b": "é", "a": None}], "a": True, "m": "line\nbreak"}
        once = canonicalize(value)
        assert canonicalize(json.loads(once)) == once


NODE = shutil.which("node")

_JS = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
// RFC 8785 reference behaviour for in-profile values: keys sorted by UTF-16
// code unit (JS default string comparison), ES6 number/string serialization.
function c(v) {
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(c).join(',') + ']';
  return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + c(v[k])).join(',') + '}';
}
process.stdout.write(c(input));
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed (cross-implementation check)")
class TestCrossImplementation:
    """Compare against an independent implementation (JavaScript's JSON.stringify)."""

    @pytest.mark.parametrize(
        "value",
        [
            {"b": 2, "a": [1, {"z": None, "y": True}], "\U0001f600": "x", "דּ": "y", "€": 0},
            {"s": 'tab\t nl\n quote" bs\\ ctl\x01\x1f del\x7f café \U0001f600'},
            {"nums": [0, -1, 9007199254740991, -9007199254740991], "empty": {}, "list": []},
            {"nested": {"kéy": {"é": ["é"]}}},
        ],
    )
    def test_matches_javascript(self, value):
        result = subprocess.run(
            [NODE, "-e", _JS],
            input=json.dumps(value).encode("utf-8"),
            capture_output=True,
            timeout=30,
            check=True,
        )
        assert canonicalize(value) == result.stdout
