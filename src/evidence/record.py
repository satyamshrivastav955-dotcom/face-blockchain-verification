"""
The verification record: construction, sealing, and integrity checking.

RECORD STRUCTURE
================
Only ``payload`` is hashed. Everything the blockchain step *produces* lives
outside it, because a hash cannot cover a transaction id that does not exist
until after the hash has been computed:

    {
      "schema":    "faceverify/v1",
      "payload":   { ... the verified claim ... },   <-- HASHED
      "integrity": { "verification_hash": "0x...", ... },
      "anchor":    { "tx_hash": "0x...", ... }       <-- written post-hash
    }

TWO CLASSES OF TAMPERING
========================
Splitting the check into a local step and a chain step catches two different
attacks, and the distinction is the whole point of anchoring:

1. *Naive edit* - the attacker changes a payload field and leaves
   ``integrity.verification_hash`` alone. The file is now self-inconsistent and
   :func:`check_local_integrity` fails offline, no network needed.

2. *Re-sealed edit* - the attacker changes a payload field **and** recomputes
   ``integrity.verification_hash`` so the file is internally consistent again.
   Nothing local can detect this; the file is a perfectly valid record of a
   different claim. Only the chain defeats it, because the recomputed hash was
   never registered on-chain and the original hash was. This is the case that
   justifies the blockchain existing at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import re

from .. import SCHEMA_VERSION, SUPPORTED_SCHEMAS
from .hashing import CanonicalizationError, canonicalize, digest_hex

__all__ = [
    "INTEGRITY_ALGORITHM",
    "LEGACY_ALGORITHM",
    "SUPPORTED_ALGORITHMS",
    "MAX_RECORD_BYTES",
    "RecordError",
    "validate_record",
    "Status",
    "LocalCheck",
    "utc_now",
    "build_payload",
    "seal",
    "attach_anchor",
    "save_record",
    "load_record",
    "check_local_integrity",
    "mutate_payload",
]

# Algorithm labels. The hashed bytes are the same for in-profile payloads, but
# the *declared* name must describe what the code really does:
#   - new records: a restricted RFC 8785 profile (no floats, |int| <= 2**53-1,
#     well-formed Unicode). See hashing.py.
#   - historical records declared plain "sha256-jcs-rfc8785"; they are verified
#     with the historical rules (legacy=True) and never silently re-labelled.
INTEGRITY_ALGORITHM = "sha256-jcs-rfc8785-restricted-v1"
LEGACY_ALGORITHM = "sha256-jcs-rfc8785"
SUPPORTED_ALGORITHMS = (INTEGRITY_ALGORITHM, LEGACY_ALGORITHM)

MAX_RECORD_BYTES = 5 * 1024 * 1024
_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class RecordError(ValueError):
    """A record file is malformed, oversized, or structurally invalid."""


class Status(Enum):
    """Outcome of a verification, mapped to process exit codes."""

    OK = 0
    LOCAL_HASH_MISMATCH = 2
    NOT_ANCHORED = 3
    ANCHOR_MISMATCH = 4
    # A required check could not be completed (RPC down, incompatible contract,
    # commitment lookup failed). Never to be read as success or as a mismatch.
    INCONCLUSIVE = 6

    @property
    def exit_code(self) -> int:
        return self.value


@dataclass
class LocalCheck:
    """Result of recomputing a record's hash from its own payload."""

    ok: bool
    stored_hash: str
    recomputed_hash: str
    canonical_length: int
    notes: list[str] = field(default_factory=list)
    algorithm: str = ""
    error: str = ""


def utc_now() -> str:
    """Current UTC time as a fixed-width ISO-8601 string, seconds precision.

    Fixed width and no microseconds keeps the hashed bytes stable and avoids
    any chance of a float or locale-dependent format entering the payload.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_payload(
    *,
    source_image: dict[str, Any],
    face: dict[str, Any],
    search: dict[str, Any],
    match: dict[str, Any],
    created_at: str | None = None,
    evidence_type: str = "",
    test_mode: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the claim that will be hashed and anchored.

    The four sections mirror the four pipeline stages, so a reader of the JSON
    can trace every assertion back to the step that produced it.
    """
    payload: dict[str, Any] = {
        "created_at": created_at or utc_now(),
        "face": face,
        "match": match,
        "schema": SCHEMA_VERSION,
        "search": search,
        "source_image": source_image,
    }
    if evidence_type:
        payload["evidence_type"] = evidence_type
    if test_mode is not None:
        payload["test_mode"] = test_mode
    return payload


def seal(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap *payload* in an envelope carrying its hash."""
    canonical = canonicalize(payload)
    return {
        "schema": SCHEMA_VERSION,
        "payload": payload,
        "integrity": {
            "algorithm": INTEGRITY_ALGORITHM,
            "verification_hash": digest_hex(payload),
            "canonical_length": len(canonical),
        },
        "anchor": None,
    }


def attach_anchor(record: dict[str, Any], anchor: dict[str, Any]) -> dict[str, Any]:
    """Record where the hash was registered on-chain.

    Mutates and returns *record*. Deliberately does not touch ``payload`` or
    ``integrity`` - if this function could change either, the hash would no
    longer describe what was signed.
    """
    record["anchor"] = anchor
    return record


def save_record(record: dict[str, Any], path: str | Path) -> Path:
    """Write *record* as indented UTF-8 JSON.

    The on-disk formatting is irrelevant to the hash - canonicalization is
    applied to the parsed object, not the file bytes - so the file is written
    human-readable on purpose, to be legible on camera during the demo.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return p


def load_record(path: str | Path) -> dict[str, Any]:
    """Read and structurally validate a record.

    Raises ``FileNotFoundError`` if missing and :class:`RecordError` for
    anything malformed (bad JSON, wrong types, missing keys, invalid hash,
    unsupported schema, oversized file).
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"no record at {p}")
    if p.stat().st_size > MAX_RECORD_BYTES:
        raise RecordError(f"{p.name}: record is larger than {MAX_RECORD_BYTES} bytes")

    def _reject_constant(name: str) -> Any:
        raise RecordError(f"{p.name}: JSON constant {name} is not allowed")

    try:
        record = json.loads(
            p.read_text(encoding="utf-8"), parse_constant=_reject_constant
        )
    except RecordError:
        raise
    except (ValueError, UnicodeDecodeError) as exc:
        raise RecordError(f"{p.name}: not valid UTF-8 JSON ({type(exc).__name__})") from exc
    except RecursionError as exc:
        raise RecordError(f"{p.name}: JSON nesting is too deep") from exc
    validate_record(record, name=p.name)
    return record


def validate_record(record: Any, *, name: str = "record") -> None:
    """Structural validation; raises :class:`RecordError`. Does not verify the hash."""
    if not isinstance(record, dict):
        raise RecordError(f"{name}: expected a JSON object at the top level")
    for key in ("payload", "integrity"):
        if key not in record:
            raise RecordError(f"{name}: record is missing required key {key!r}")
    payload, integrity = record["payload"], record["integrity"]
    if not isinstance(payload, dict):
        raise RecordError(f"{name}: 'payload' must be an object")
    if not isinstance(integrity, dict):
        raise RecordError(f"{name}: 'integrity' must be an object")
    stored = integrity.get("verification_hash")
    if not isinstance(stored, str) or not _HASH_RE.match(stored):
        raise RecordError(f"{name}: integrity.verification_hash must be 0x + 64 hex digits")
    schema = record.get("schema", payload.get("schema"))
    if schema not in SUPPORTED_SCHEMAS:
        raise RecordError(f"{name}: unsupported schema {str(schema)[:40]!r}")
    anchor = record.get("anchor")
    if anchor is not None and not isinstance(anchor, dict):
        raise RecordError(f"{name}: 'anchor' must be an object or null")
    match = payload.get("match")
    if match is not None and not isinstance(match, dict):
        raise RecordError(f"{name}: payload.match must be an object")
    source = payload.get("source_image")
    if source is not None and not isinstance(source, dict):
        raise RecordError(f"{name}: payload.source_image must be an object")
    if isinstance(match, dict) and "matched_url" in match and not isinstance(match["matched_url"], str):
        raise RecordError(f"{name}: payload.match.matched_url must be a string")


def check_local_integrity(record: dict[str, Any]) -> LocalCheck:
    """Recompute the payload hash under the record's *declared* algorithm.

    Catches tampering class 1 (naive edit) entirely offline. A record declaring
    an algorithm this build does not implement is reported as failed: it is
    never re-interpreted under a different algorithm.
    """
    payload = record["payload"]
    integrity = record.get("integrity") or {}
    stored = str(integrity.get("verification_hash", ""))
    algorithm = integrity.get("algorithm")
    notes: list[str] = []

    if algorithm not in SUPPORTED_ALGORITHMS:
        return LocalCheck(
            ok=False,
            stored_hash=stored,
            recomputed_hash="",
            canonical_length=0,
            algorithm=str(algorithm),
            error=(
                f"unsupported integrity algorithm {str(algorithm)[:60]!r}; this build "
                f"supports {', '.join(SUPPORTED_ALGORITHMS)}"
            ),
        )
    legacy = algorithm == LEGACY_ALGORITHM
    if legacy:
        notes.append(
            "historical record: sealed under the earlier algorithm label "
            f"{LEGACY_ALGORITHM!r}; verified with its original rules"
        )
    try:
        recomputed = digest_hex(payload, legacy=legacy)
        canonical_length = len(canonicalize(payload, legacy=legacy))
    except (CanonicalizationError, RecursionError) as exc:
        return LocalCheck(
            ok=False,
            stored_hash=stored,
            recomputed_hash="",
            canonical_length=0,
            algorithm=str(algorithm),
            error=f"payload cannot be canonicalized: {str(exc)[:160]}",
        )

    declared_length = integrity.get("canonical_length")
    if isinstance(declared_length, int) and declared_length != canonical_length:
        notes.append(
            f"canonical length changed: sealed at {declared_length} bytes, now "
            f"{canonical_length} bytes"
        )

    return LocalCheck(
        ok=bool(stored) and stored.lower() == recomputed.lower(),
        stored_hash=stored,
        recomputed_hash=recomputed,
        canonical_length=canonical_length,
        notes=notes,
        algorithm=str(algorithm),
    )


def mutate_payload(record: dict[str, Any], dotted_field: str, new_value: Any) -> Any:
    """Set ``payload.<dotted_field>`` to *new_value*, returning the old value.

    Used only by the ``tamper-demo`` command to simulate an attacker editing
    the evidence. Raises if the path does not exist, so the demo cannot
    silently "tamper" with a field that was never there.
    """
    parts = dotted_field.split(".")
    node: Any = record["payload"]
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"payload has no field {dotted_field!r}")
        node = node[part]
    leaf = parts[-1]
    if not isinstance(node, dict) or leaf not in node:
        raise KeyError(f"payload has no field {dotted_field!r}")
    old = node[leaf]
    node[leaf] = new_value
    return old
