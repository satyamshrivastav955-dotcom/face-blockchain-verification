"""
C2PA Content Credentials: read and summarise an image's embedded provenance manifest.

C2PA (https://c2pa.org) is the industry standard for signed provenance metadata: a
manifest embedded in the file says which tool produced or edited it, what edits were
applied, and carries a signature that breaks if the pixels or the claim are altered.
Cameras, editing tools and generative-AI services increasingly write it. Reading it is
*independent* evidence of an image's origin: it does not depend on a search engine, a
face model or a perceptual hash.

WHAT IS AND IS NOT CLAIMED
==========================
* ``state`` reports what the C2PA SDK found: ``absent`` (no manifest - the common case,
  and NOT evidence of anything), ``valid`` / ``invalid`` (signature and hash checks), or
  ``unavailable`` / ``error`` / ``unsupported_format``.
* ``valid`` means the manifest is internally consistent and the signature verifies. It does
  NOT mean the signer is trusted: ``untrusted_signer`` is set when the SDK reports the
  signing certificate is not on a trust list (e.g. test certificates). Trust is a policy
  decision this tool does not make.
* A manifest can be stripped by re-encoding or screenshots; its absence proves nothing.
* ``ai_generated`` is true only when the manifest itself declares a generative-AI digital
  source type. It is a statement by the signer, not a detector.

The ``c2pa-python`` dependency is optional; without it the state is ``unavailable``.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Any

__all__ = ["ContentCredentials", "inspect_content_credentials", "summarise_manifest_store"]

_MIME = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
)
_AI_SOURCE_TYPES = ("trainedalgorithmicmedia", "compositewithtrainedalgorithmicmedia", "algorithmicmedia")
MAX_LIST = 20


@dataclass
class ContentCredentials:
    state: str = "absent"  # absent | valid | invalid | unavailable | unsupported_format | error
    validation_state: str = ""  # the SDK's own label: Valid / Trusted / Invalid
    untrusted_signer: bool = False
    issuer: str = ""
    signer_common_name: str = ""
    signing_algorithm: str = ""
    signed_at: str = ""
    claim_generator: str = ""
    actions: list[str] = field(default_factory=list)
    ai_generated: bool = False
    ingredients: int = 0
    failure_codes: list[str] = field(default_factory=list)
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        """Hash-safe summary: strings, ints and bools only."""
        return {
            "state": self.state,
            "validation_state": self.validation_state,
            "untrusted_signer": bool(self.untrusted_signer),
            "issuer": self.issuer[:120],
            "signer_common_name": self.signer_common_name[:120],
            "signing_algorithm": self.signing_algorithm,
            "signed_at": self.signed_at,
            "claim_generator": self.claim_generator[:120],
            "actions": self.actions[:MAX_LIST],
            "ai_generated": bool(self.ai_generated),
            "ingredients": int(self.ingredients),
            "failure_codes": self.failure_codes[:MAX_LIST],
            "detail": self.detail[:160],
        }


def _mime(data: bytes) -> str:
    for magic, mime in _MIME:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def summarise_manifest_store(store: dict[str, Any]) -> ContentCredentials:
    """Turn the SDK's manifest-store JSON into a :class:`ContentCredentials` (pure; unit-testable)."""
    out = ContentCredentials()
    active = store.get("active_manifest")
    manifest = (store.get("manifests") or {}).get(active) if active else None
    if not isinstance(manifest, dict):
        out.state = "absent"
        return out

    out.validation_state = str(store.get("validation_state", ""))
    codes = [str(s.get("code", "")) for s in (store.get("validation_status") or []) if isinstance(s, dict)]
    out.failure_codes = codes
    out.untrusted_signer = any("untrusted" in c.lower() for c in codes)
    hard_failures = [c for c in codes if c and "untrusted" not in c.lower()]
    out.state = "invalid" if (out.validation_state.lower() == "invalid" or hard_failures) else "valid"

    sig = manifest.get("signature_info") or {}
    out.issuer = str(sig.get("issuer", ""))
    out.signer_common_name = str(sig.get("common_name", ""))
    out.signing_algorithm = str(sig.get("alg", ""))
    out.signed_at = str(sig.get("time", ""))
    infos = manifest.get("claim_generator_info") or []
    names = [str(i.get("name", "")) for i in infos if isinstance(i, dict) and i.get("name")]
    out.claim_generator = ", ".join(names) or str(manifest.get("claim_generator", ""))
    out.ingredients = len(manifest.get("ingredients") or [])

    for assertion in manifest.get("assertions") or []:
        if not isinstance(assertion, dict) or not str(assertion.get("label", "")).startswith("c2pa.actions"):
            continue
        for action in (assertion.get("data") or {}).get("actions", []) or []:
            if not isinstance(action, dict):
                continue
            if action.get("action"):
                out.actions.append(str(action["action"]))
            source = str(action.get("digitalSourceType", "")).lower()
            if any(t in source for t in _AI_SOURCE_TYPES):
                out.ai_generated = True
    out.actions = list(dict.fromkeys(out.actions))
    return out


def inspect_content_credentials(data: bytes) -> ContentCredentials:
    """Read C2PA Content Credentials from image bytes. Never raises."""
    mime = _mime(data)
    if not mime:
        return ContentCredentials(state="unsupported_format", detail="C2PA reading supports JPEG, PNG, WebP, GIF here")
    try:
        import c2pa
    except ImportError:
        return ContentCredentials(state="unavailable", detail="c2pa-python is not installed")
    try:
        reader = c2pa.Reader(mime, io.BytesIO(data))
        store = json.loads(reader.json())
    except Exception as exc:  # noqa: BLE001 - the SDK raises on "no manifest" as well as on corruption
        text = str(exc).lower()
        if "manifestnotfound" in text.replace(" ", "") or "no manifest" in text or "jumbf" in text:
            return ContentCredentials(state="absent")
        return ContentCredentials(state="error", detail=f"{type(exc).__name__}")
    try:
        return summarise_manifest_store(store)
    except Exception as exc:  # noqa: BLE001
        return ContentCredentials(state="error", detail=f"unreadable manifest ({type(exc).__name__})")
