"""
Ed25519 signatures over a record's verification hash.

WHY THIS EXISTS
===============
A bare hash proves a record is *self-consistent*; it says nothing about who made it. Anyone can
build a record about any image, hash it and anchor it. A signature adds an *author*: a key whose
public half a verifier can pin ("only accept records signed by this key").

WHAT IS AND IS NOT CLAIMED
==========================
* The signature covers exactly ``domain_tag || verification_hash`` (32 bytes). The hash already
  commits to the whole payload, so the signature transitively covers every claim in it.
* ``valid`` means "this key signed this hash". It does NOT mean the key belongs to any particular
  person or organisation, nor that the claim is true. Identity binding is a policy decision made by
  *pinning* a public key out of band (``--trusted-key``); an unpinned valid signature is reported as
  ``pinned=False``-or-``None`` and must never be presented as an identity proof.
* The signature lives outside the hashed payload (like ``anchor``), so adding it never changes the
  hash. A forger who re-seals an edited payload cannot produce a valid signature without the key.
* Key compromise, key rotation and revocation are NOT handled here.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SIGNATURE_ALGORITHM = "ed25519"
_DOMAIN = b"faceproof-record-v1\x00"
_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_HEX32 = re.compile(r"^[0-9a-fA-F]{64}$")


class SigningError(ValueError):
    """A key could not be generated, read or used."""


def _crypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:  # pragma: no cover - cryptography ships with c2pa-python/web3
        raise SigningError("the 'cryptography' package is required for signing") from exc
    return InvalidSignature, serialization, ed25519


def generate_key(path: str | Path, *, overwrite: bool = False) -> str:
    """Create a new Ed25519 private key (PEM, PKCS#8, unencrypted) and return its public key hex.

    The file is created exclusively (never overwrites unless asked) and, where the OS supports it,
    readable only by the owner. Keep it out of the repository: ``*.pem`` and ``*.key`` are git-ignored.
    """
    _, serialization, ed25519 = _crypto()
    target = Path(path)
    if target.exists() and not overwrite:
        raise SigningError(f"{target} already exists; refusing to overwrite a signing key")
    target.parent.mkdir(parents=True, exist_ok=True)
    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL) | getattr(os, "O_BINARY", 0)
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    return public_key_hex(key)


def load_private_key(path: str | Path):
    _, serialization, ed25519 = _crypto()
    p = Path(path)
    if not p.is_file():
        raise SigningError(f"no signing key at {p}")
    try:
        key = serialization.load_pem_private_key(p.read_bytes(), password=None)
    except Exception as exc:  # noqa: BLE001
        raise SigningError(f"{p.name}: not a readable unencrypted PEM private key ({type(exc).__name__})") from exc
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise SigningError(f"{p.name}: not an Ed25519 key")
    return key


def public_key_hex(key: Any) -> str:
    """Raw 32-byte public key as lowercase hex (accepts a private or public key object)."""
    _, serialization, _ = _crypto()
    pub = key.public_key() if hasattr(key, "public_key") else key
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def load_public_key_hex(value: str) -> str:
    """Normalise a trusted key given as 64 hex chars, or as a path to a hex / PEM public key file."""
    _, serialization, ed25519 = _crypto()
    text = value.strip()
    if _HEX32.match(text):
        return text.lower()
    p = Path(text)
    if not p.is_file():
        raise SigningError("trusted key must be 64 hex characters or the path of a public-key file")
    raw = p.read_bytes()
    stripped = raw.decode("ascii", errors="ignore").strip()
    if _HEX32.match(stripped):
        return stripped.lower()
    try:
        pub = serialization.load_pem_public_key(raw)
    except Exception as exc:  # noqa: BLE001
        raise SigningError(f"{p.name}: not a hex or PEM Ed25519 public key") from exc
    if not isinstance(pub, ed25519.Ed25519PublicKey):
        raise SigningError(f"{p.name}: not an Ed25519 public key")
    return public_key_hex(pub)


def key_id(public_hex: str) -> str:
    """Short, stable identifier for a public key (first 16 hex chars of its SHA-256)."""
    return hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()[:16]


def _message(verification_hash: str) -> bytes:
    if not _HASH_RE.match(verification_hash):
        raise SigningError("verification hash must be 0x + 64 hex digits")
    return _DOMAIN + bytes.fromhex(verification_hash[2:])


def sign_record(record: dict[str, Any], private_key: Any) -> dict[str, Any]:
    """Attach ``record['signature']`` for the record's current verification hash. Returns *record*."""
    vhash = str((record.get("integrity") or {}).get("verification_hash", ""))
    pub = public_key_hex(private_key)
    record["signature"] = {
        "algorithm": SIGNATURE_ALGORITHM,
        "public_key": pub,
        "key_id": key_id(pub),
        "signed_hash": vhash.lower(),
        "signature": private_key.sign(_message(vhash.lower())).hex(),
    }
    return record


@dataclass
class SignatureCheck:
    """state: unsigned | valid | invalid.  pinned: None when no trusted keys were supplied."""

    state: str
    pinned: bool | None = None
    public_key: str = ""
    key_id: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        """True when the record may proceed: unsigned, or valid (and pinned when pinning was requested)."""
        return self.state != "invalid" and self.pinned is not False


def check_signature(
    record: dict[str, Any], recomputed_hash: str, trusted_keys: list[str] | None = None
) -> SignatureCheck:
    """Verify ``record['signature']`` against the *recomputed* payload hash (never the stored one).

    With ``trusted_keys`` the signer must be one of them; a record with no signature then FAILS
    (an unsigned record cannot satisfy a pinning requirement).
    """
    pinned_set = {load_public_key_hex(k) for k in trusted_keys} if trusted_keys else None
    sig = record.get("signature")
    if sig is None:
        if pinned_set:
            return SignatureCheck(
                "invalid", pinned=False, detail="a trusted key was required but the record is unsigned"
            )
        return SignatureCheck("unsigned", detail="the record carries no signature")
    if not isinstance(sig, dict):
        return SignatureCheck("invalid", detail="signature block is malformed")
    if sig.get("algorithm") != SIGNATURE_ALGORITHM:
        return SignatureCheck("invalid", detail=f"unsupported signature algorithm {str(sig.get('algorithm'))[:30]!r}")
    pub, raw_sig, signed_hash = sig.get("public_key"), sig.get("signature"), sig.get("signed_hash")
    if not (isinstance(pub, str) and _HEX32.match(pub) and isinstance(raw_sig, str) and isinstance(signed_hash, str)):
        return SignatureCheck("invalid", detail="signature block is malformed")
    if signed_hash.lower() != recomputed_hash.lower():
        return SignatureCheck(
            "invalid",
            public_key=pub.lower(),
            key_id=key_id(pub),
            detail="signature covers a different hash than the payload now has",
        )
    InvalidSignature, _, ed25519 = _crypto()
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub)).verify(
            bytes.fromhex(raw_sig), _message(recomputed_hash.lower())
        )
    except (InvalidSignature, ValueError):
        return SignatureCheck("invalid", public_key=pub.lower(), key_id=key_id(pub), detail="signature does not verify")
    pinned = None if pinned_set is None else (pub.lower() in pinned_set)
    detail = "valid signature; signer key NOT pinned (proves consistency, not identity)"
    if pinned is True:
        detail = "valid signature by a pinned key"
    elif pinned is False:
        detail = "valid signature, but by a key that is not in the trusted set"
    return SignatureCheck("valid", pinned=pinned, public_key=pub.lower(), key_id=key_id(pub), detail=detail)
