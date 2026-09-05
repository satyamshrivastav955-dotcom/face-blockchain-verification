"""
Deterministic JSON canonicalization and hashing.

WHY THIS MODULE EXISTS
======================
`verify` must reproduce a *byte-identical* serialization of the verification
payload days after `register` wrote it, possibly on a different machine and a
different Python version. Plain ``json.dumps`` does not guarantee that: key
ordering, float repr, unicode escaping and whitespace can all vary. One
differing byte changes the SHA-256, and an untampered record then reports as
tampered. That failure is intermittent and extremely expensive to debug, so
canonicalization is treated as a first-class, separately tested component.

We follow RFC 8785 (JSON Canonicalization Scheme):

  * object keys sorted by UTF-16 code unit  (not Python's default code-point
    order - see ``_utf16_sort_key``)
  * no insignificant whitespace            -> separators are "," and ":"
  * unicode emitted literally as UTF-8     -> no \\uXXXX escapes
  * output encoded as UTF-8

...with one deliberate tightening: **floats are rejected outright.** RFC 8785
specifies float serialization via the ES6 ``Number::toString`` algorithm, which
CPython's ``repr`` does not implement. Rather than ship a subtly non-compliant
float serializer, we forbid floats in payloads entirely. Every number in a
verification record is either an exact integer (counts, pixel coordinates,
timestamps) or a score we control, and scores are stored as fixed-precision
*strings* via :func:`fmt_score`. A float reaching this module is a bug.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

__all__ = [
    "CanonicalizationError",
    "canonicalize",
    "digest",
    "digest_hex",
    "fmt_score",
    "sha256_bytes",
    "sha256_file",
]

# Read files in 1 MiB chunks so a large image never has to sit in memory twice.
_CHUNK = 1024 * 1024


class CanonicalizationError(TypeError):
    """A value cannot be canonicalized deterministically."""


def _utf16_sort_key(s: str) -> bytes:
    """Sort key giving RFC 8785 ordering (UTF-16 code units).

    Python compares ``str`` by Unicode code point. RFC 8785 requires ordering
    by UTF-16 code unit, and the two disagree for supplementary characters
    (U+10000 and above), which encode as surrogate pairs beginning 0xD800-
    0xDBFF and therefore sort *before* BMP characters in U+E000-U+FFFF.
    Encoding to big-endian UTF-16 and comparing the raw bytes reproduces the
    required order exactly.

    Our own schema keys are all ASCII, where the orders coincide - this is
    here so that URLs, titles or platform names carrying exotic characters
    cannot silently break interoperability with other JCS implementations.
    """
    return s.encode("utf-16-be", errors="surrogatepass")


def _encode_string(s: str) -> str:
    """Serialize a JSON string per RFC 8785.

    ``json.dumps`` with ``ensure_ascii=False`` already implements exactly the
    escaping RFC 8785 mandates: escape only ``"``, ``\\`` and the C0 control
    characters, preferring the two-character forms (\\b \\t \\n \\f \\r) and
    falling back to \\u00XX; emit every other character literally.
    """
    return json.dumps(s, ensure_ascii=False)


def _write(value: Any, out: list[str], path: str) -> None:
    """Recursively append the canonical form of *value* to *out*.

    *path* is a dotted breadcrumb used only to make error messages actionable.
    """
    # bool must be tested before int: isinstance(True, int) is True in Python.
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
        out.append(_encode_string(value))
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        raise CanonicalizationError(
            f"float at {path!r} (value {value!r}): floats are not canonicalizable "
            "here. Use an int for exact quantities, or fmt_score() to store a "
            "score as a fixed-precision string."
        )
    elif isinstance(value, Decimal):
        raise CanonicalizationError(
            f"Decimal at {path!r}: convert to str (or int) before hashing so the "
            "serialized precision is explicit and stable."
        )
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError(
                    f"non-string object key {key!r} at {path!r}: JSON object keys "
                    "must be strings, and coercing them would be ambiguous."
                )
        out.append("{")
        for i, key in enumerate(sorted(value, key=_utf16_sort_key)):
            if i:
                out.append(",")
            out.append(_encode_string(key))
            out.append(":")
            _write(value[key], out, f"{path}.{key}" if path else key)
        out.append("}")
    elif isinstance(value, (list, tuple)):
        # Array order is significant and is preserved verbatim.
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _write(item, out, f"{path}[{i}]")
        out.append("]")
    else:
        raise CanonicalizationError(
            f"unsupported type {type(value).__name__} at {path!r}: only dict, "
            "list, str, int, bool and None can appear in a hashed payload."
        )


def canonicalize(obj: Any) -> bytes:
    """Return the RFC 8785 canonical UTF-8 encoding of *obj*."""
    parts: list[str] = []
    _write(obj, parts, "")
    return "".join(parts).encode("utf-8")


def digest(obj: Any) -> bytes:
    """SHA-256 of the canonical encoding of *obj* (32 raw bytes)."""
    return hashlib.sha256(canonicalize(obj)).digest()


def digest_hex(obj: Any, prefix: bool = True) -> str:
    """SHA-256 of the canonical encoding of *obj* as hex.

    With ``prefix=True`` the result is ``0x``-prefixed, which is the form the
    smart contract expects for a ``bytes32`` argument.
    """
    h = hashlib.sha256(canonicalize(obj)).hexdigest()
    return f"0x{h}" if prefix else h


def fmt_score(x: float, places: int = 4) -> str:
    """Format a similarity score as a fixed-precision string.

    Scores originate as floats from OpenCV, but a float cannot go into a hashed
    payload (see the module docstring). Rounding to a fixed number of decimal
    places and storing the *string* makes the hashed value unambiguous and
    stable, while staying human-readable in the record and on screen.
    """
    if x != x:  # NaN
        raise CanonicalizationError("refusing to format NaN as a score")
    if x in (float("inf"), float("-inf")):
        raise CanonicalizationError("refusing to format an infinite score")
    return f"{float(x):.{places}f}"


def sha256_bytes(data: bytes, prefix: bool = False) -> str:
    """SHA-256 of raw bytes, as hex."""
    h = hashlib.sha256(data).hexdigest()
    return f"0x{h}" if prefix else h


def sha256_file(path: str | Path, prefix: bool = False) -> str:
    """SHA-256 of a file's contents, as hex, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            h.update(block)
    return f"0x{h.hexdigest()}" if prefix else h.hexdigest()
