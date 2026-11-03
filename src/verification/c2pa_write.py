"""
Write a FaceProof reference into a C2PA manifest so the record travels with the file.

WHAT GETS WRITTEN
=================
A standard C2PA manifest signed with a certificate YOU provide, containing one custom assertion,
``org.faceproof.record``: the record's verification hash, its schema and (if the record is signed) the
FaceProof key id. C2PA's own hard binding ties the manifest to the pixels of the new file, so any
pixel edit afterwards invalidates it. An existing manifest is kept as the parent ingredient (an
``EDIT``), never silently replaced.

WHAT THIS DOES NOT DO
=====================
* It does not make a certificate trustworthy. A self-made certificate produces a manifest that
  validates but whose signer is ``untrusted``; only a certificate on the official C2PA Trust List is
  recognised as trusted by conformant readers, and obtaining one is a business process this tool
  cannot perform for you.
* Embedding changes the file's bytes, so the new file has a different SHA-256 than the one inside the
  FaceProof record, which describes the file *as attested*. The assertion therefore also stores
  ``source_sha256`` (the attested bytes) and a verifier checks ``record <-> assertion``, not
  ``record <-> embedded file``.
* The assertion is a pointer, not the record. The record itself still has to be stored and checked.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from .c2pa_check import FACEPROOF_ASSERTION, _mime

__all__ = ["C2paWriteError", "embed_record_reference"]

_ALGS = ("ES256", "ES384", "ES512", "PS256", "PS384", "PS512", "ED25519")


class C2paWriteError(RuntimeError):
    """Embedding failed (missing SDK, bad certificate, unsupported format)."""


def embed_record_reference(
    image_bytes: bytes,
    record: dict[str, Any],
    *,
    cert_chain_pem: str,
    private_key_pem: str,
    alg: str = "ES256",
    title: str = "image",
) -> bytes:
    """Return *image_bytes* with a signed C2PA manifest referencing *record*."""
    mime = _mime(image_bytes)
    if not mime:
        raise C2paWriteError("C2PA embedding supports JPEG, PNG, WebP and GIF here")
    if alg.upper() not in _ALGS:
        raise C2paWriteError(f"unsupported signing algorithm {alg!r} (expected one of {', '.join(_ALGS)})")
    try:
        import c2pa
    except ImportError as exc:
        raise C2paWriteError("c2pa-python is not installed") from exc

    integrity = record.get("integrity") or {}
    payload = record.get("payload") or {}
    signature = record.get("signature") or {}
    vhash = str(integrity.get("verification_hash", ""))
    if not (len(vhash) == 66 and vhash.startswith("0x")):
        raise C2paWriteError("record has no valid verification hash")
    assertion = {
        "verification_hash": vhash,
        "schema": str(record.get("schema", "")),
        "source_sha256": str((payload.get("source_image") or {}).get("sha256", "")),
        "key_id": str(signature.get("key_id", "")),
    }
    manifest = {
        "claim_generator_info": [{"name": "faceproof", "version": "2"}],
        "title": title[:80],
        "assertions": [{"label": FACEPROOF_ASSERTION, "data": assertion}],
    }
    try:
        info = c2pa.C2paSignerInfo(
            getattr(c2pa.C2paSigningAlg, alg.upper()), cert_chain_pem.encode(), private_key_pem.encode(), None
        )
        signer = c2pa.Signer.from_info(info)
        builder = c2pa.Builder(json.dumps(manifest))
        builder.set_intent(c2pa.C2paBuilderIntent.EDIT)
        out = io.BytesIO()
        builder.sign(signer, mime, io.BytesIO(image_bytes), out)
    except Exception as exc:  # noqa: BLE001 - the SDK raises its own error types
        raise C2paWriteError(f"C2PA signing failed ({type(exc).__name__}): {str(exc)[:200]}") from exc
    return out.getvalue()


def read_pem(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise C2paWriteError(f"no such file: {p}")
    return p.read_text(encoding="utf-8")
