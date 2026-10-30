"""
Batched anchoring: leaves, proofs, and the record-side proof check.

A batch registers ONE Merkle root on-chain for N verification records. Each record then
carries, in its (unhashed) ``anchor`` block, the proof that ties it to that root:

    "anchor": {
        "mode": "merkle_batch",
        "merkle": {"root": "0x..", "index": 3, "size": 8, "proof": ["0x..", ..],
                   "leaf": "verification_hash || url_commitment"},
        ... tx / block fields of the single batch transaction ...
    }

LEAF
----
``leaf_data = verification_hash (32 bytes) || keccak256(matched_url) (32 bytes)``, hashed
with the RFC 6962 leaf prefix. Binding the URL commitment into the leaf means a verified
inclusion proof also proves the URL commitment - exactly what the per-record contract
stored - without a second on-chain lookup. Both halves are *recomputed from the record*
at verification time; the stored ``merkle`` block is never trusted for them.

TRUST
-----
This changes nothing about what anchoring proves (a hash was registered at a time). It
changes the cost: one transaction for N records, and proofs of about log2(N) hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .merkle import inclusion_proof, merkle_root, verify_inclusion

__all__ = ["BatchPlan", "ProofCheck", "leaf_data", "build_batch", "merkle_block", "check_record_proof"]

LEAF_DESCRIPTION = "RFC6962 leaf over verification_hash||keccak256(matched_url)"


class BatchError(ValueError):
    """Raised when a batch is malformed (duplicate leaves, bad hex, out-of-range proof)."""


def _bytes32(hex_str: str, what: str) -> bytes:
    """Parse a 32-byte value from a 0x-prefixed or plain hex string; raise :class:`BatchError` on failure."""
    text = hex_str[2:] if hex_str.startswith("0x") else hex_str
    try:
        raw = bytes.fromhex(text)
    except ValueError as exc:
        raise BatchError(f"{what} is not hex") from exc
    if len(raw) != 32:
        raise BatchError(f"{what} must be 32 bytes")
    return raw


def leaf_data(verification_hash: str, url_commit: str) -> bytes:
    """Concatenate the two 32-byte values that form an RFC 6962 leaf in a batch.

    The leaf is ``verification_hash (32 bytes) || keccak256(matched_url) (32 bytes)``.
    Both halves are recomputed from the record at verification time; the stored
    ``merkle`` block is never trusted as the canonical source for them.
    """
    return _bytes32(verification_hash, "verification_hash") + _bytes32(url_commit, "url_commitment")


@dataclass
class BatchPlan:
    root: str
    size: int
    leaves: list[bytes]
    proofs: list[list[str]]


def build_batch(entries: list[tuple[str, str]]) -> BatchPlan:
    """entries: ``(verification_hash, url_commitment)`` per record, in batch order."""
    if not entries:
        raise BatchError("a batch needs at least one record")
    leaves = [leaf_data(h, u) for h, u in entries]
    if len({x for x in leaves}) != len(leaves):
        raise BatchError("duplicate record in batch")
    root = merkle_root(leaves)
    proofs = [["0x" + p.hex() for p in inclusion_proof(leaves, i)] for i in range(len(leaves))]
    return BatchPlan(root="0x" + root.hex(), size=len(leaves), leaves=leaves, proofs=proofs)


def merkle_block(plan: BatchPlan, index: int) -> dict[str, Any]:
    """Return the ``merkle`` sub-dict to embed in a record's ``anchor`` at *index* in *plan*."""
    return {
        "root": plan.root,
        "index": index,
        "size": plan.size,
        "proof": plan.proofs[index],
        "leaf": LEAF_DESCRIPTION,
    }


@dataclass
class ProofCheck:
    ok: bool
    root: str = ""
    reason: str = ""


def check_record_proof(verification_hash: str, url_commit: str, merkle: Any) -> ProofCheck:
    """Verify that this record's leaf, recomputed from its own data, is in ``merkle['root']``."""
    if not isinstance(merkle, dict):
        return ProofCheck(False, reason="no merkle proof in the record's anchor")
    try:
        root = merkle.get("root", "")
        index, size = merkle.get("index"), merkle.get("size")
        proof = merkle.get("proof")
        if not (isinstance(index, int) and isinstance(size, int) and isinstance(proof, list)):
            return ProofCheck(False, reason="malformed merkle block")
        if not 1 <= size < 2**32 or len(proof) > 64:
            return ProofCheck(False, reason="implausible merkle block")
        root_bytes = _bytes32(root, "merkle root")
        proof_bytes = [_bytes32(p, "proof element") for p in proof]
        leaf = leaf_data(verification_hash, url_commit)
    except (BatchError, TypeError, AttributeError) as exc:
        return ProofCheck(False, reason=str(exc)[:120])
    if not verify_inclusion(leaf, index, size, proof_bytes, root_bytes):
        return ProofCheck(False, root=root, reason="the proof does not lead from this record to the root")
    return ProofCheck(True, root=root)
