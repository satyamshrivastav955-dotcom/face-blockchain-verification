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

from .. import SCHEMA_VERSION
from .hashing import canonicalize, digest_hex

__all__ = [
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

INTEGRITY_ALGORITHM = "sha256-jcs-rfc8785"


class Status(Enum):
    """Outcome of a verification, mapped to process exit codes."""

    OK = 0
    LOCAL_HASH_MISMATCH = 2
    NOT_ANCHORED = 3
    ANCHOR_MISMATCH = 4

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
) -> dict[str, Any]:
    """Assemble the claim that will be hashed and anchored.

    The four sections mirror the four pipeline stages, so a reader of the JSON
    can trace every assertion back to the step that produced it.
    """
    return {
        "created_at": created_at or utc_now(),
        "face": face,
        "match": match,
        "schema": SCHEMA_VERSION,
        "search": search,
        "source_image": source_image,
    }


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
    """Read a record from disk, with schema sanity checks."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no record at {p}")
    record = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError(f"{p}: expected a JSON object at the top level")
    for key in ("payload", "integrity"):
        if key not in record:
            raise ValueError(f"{p}: record is missing required key {key!r}")
    return record


def check_local_integrity(record: dict[str, Any]) -> LocalCheck:
    """Recompute the payload hash and compare it to the stored one.

    Catches tampering class 1 (naive edit) entirely offline.
    """
    payload = record["payload"]
    integrity = record.get("integrity") or {}
    stored = str(integrity.get("verification_hash", ""))
    recomputed = digest_hex(payload)
    canonical_length = len(canonicalize(payload))

    notes: list[str] = []
    algorithm = integrity.get("algorithm")
    if algorithm and algorithm != INTEGRITY_ALGORITHM:
        notes.append(
            f"record was sealed with algorithm {algorithm!r}, this build uses "
            f"{INTEGRITY_ALGORITHM!r}"
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
