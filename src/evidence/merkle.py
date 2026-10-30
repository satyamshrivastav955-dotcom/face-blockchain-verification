"""
Merkle tree with RFC 6962 / RFC 9162 hashing, for batched anchoring.

WHY
===
Anchoring one transaction per record costs one gas payment and one block slot per
record. A Merkle batch registers a *single* 32-byte root for N records; each record
keeps a short inclusion proof (about log2 N hashes) that ties it to that root. This is
the scheme Certificate Transparency logs and OpenTimestamps-style services use.

HASHING (RFC 6962 section 2.1, identical in RFC 9162)
-----------------------------------------------------
* leaf hash:  SHA-256(0x00 || leaf_data)
* node hash:  SHA-256(0x01 || left || right)
* empty tree: SHA-256("")
* a tree of n > 1 leaves splits at k, the largest power of two strictly less than n:
  MTH(D[0:n]) = H(0x01 || MTH(D[0:k]) || MTH(D[k:n])).

The distinct 0x00 / 0x01 prefixes make leaves and interior nodes domain-separated, which
prevents second-preimage attacks that pass an interior node off as a leaf.

Inclusion proofs follow RFC 6962 2.1.1; verification follows the iterative algorithm of
RFC 9162 2.1.3.2 (it also checks that the proof has exactly the right length).
"""

from __future__ import annotations

import hashlib

__all__ = [
    "EMPTY_ROOT",
    "leaf_hash",
    "node_hash",
    "merkle_root",
    "inclusion_proof",
    "verify_inclusion",
]

EMPTY_ROOT = hashlib.sha256(b"").digest()


def leaf_hash(data: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(n: int) -> int:
    """Largest power of two strictly less than *n* (n >= 2)."""
    return 1 << ((n - 1).bit_length() - 1)


def _root(hashes: list[bytes]) -> bytes:
    n = len(hashes)
    if n == 0:
        return EMPTY_ROOT
    if n == 1:
        return hashes[0]
    k = _split(n)
    return node_hash(_root(hashes[:k]), _root(hashes[k:]))


def merkle_root(leaves: list[bytes]) -> bytes:
    """Root over *leaves* (raw leaf data, hashed here)."""
    return _root([leaf_hash(x) for x in leaves])


def _path(index: int, hashes: list[bytes]) -> list[bytes]:
    n = len(hashes)
    if n <= 1:
        return []
    k = _split(n)
    if index < k:
        return _path(index, hashes[:k]) + [_root(hashes[k:])]
    return _path(index - k, hashes[k:]) + [_root(hashes[:k])]


def inclusion_proof(leaves: list[bytes], index: int) -> list[bytes]:
    """Audit path for ``leaves[index]``, ordered leaf-to-root."""
    if not 0 <= index < len(leaves):
        raise IndexError("leaf index out of range")
    return _path(index, [leaf_hash(x) for x in leaves])


def verify_inclusion(leaf_data: bytes, index: int, size: int, proof: list[bytes], root: bytes) -> bool:
    """RFC 9162 2.1.3.2: recompute the root from a leaf and its audit path and compare."""
    if not 0 <= index < size:
        return False
    fn, sn = index, size - 1
    r = leaf_hash(leaf_data)
    for p in proof:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = node_hash(p, r)
            if not fn & 1:
                while fn and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            r = node_hash(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == root
