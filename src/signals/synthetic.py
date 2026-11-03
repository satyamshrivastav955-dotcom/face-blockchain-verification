"""
Synthetic-media signals read from the file itself.

WHAT THIS IS
============
Deterministic extraction of *declarations* that a generator or editing tool wrote into the file:

* an IPTC / C2PA ``digitalSourceType`` naming generative AI (``trainedAlgorithmicMedia`` and friends);
* PNG text chunks that popular local generators write (``parameters``, ``prompt``, ``workflow``);
* a generator name in the XMP packet or in PNG ``Software`` / ``Comment`` text.

WHAT THIS IS NOT
================
* It is NOT a detector. There is no classifier here, deliberately: published 2026 benchmarks show
  open AI-image detectors failing on newer generators and collapsing under JPEG compression
  (docs/DECISIONS.md D6). Shipping one would produce confident numbers with no defensible error rate.
* ``declared_synthetic`` is a statement by whoever wrote the metadata, who may be the generator, an
  editor, or an attacker adding a false label. It is evidence about a *claim*, not about the pixels.
* ``no_declaration`` carries NO information: metadata is stripped by screenshots, re-encoding and most
  social platforms. It must never be rendered as "authentic", "real" or "human-made".

Everything returned is strings / ints / bools so it can sit inside a hashed record.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Any

__all__ = ["SyntheticSignals", "extract_synthetic_signals"]

_AI_SOURCE_TYPES = ("trainedalgorithmicmedia", "compositewithtrainedalgorithmicmedia", "algorithmicmedia")
_PNG_PARAM_KEYS = {"parameters", "prompt", "workflow", "invokeai_metadata", "sd-metadata"}
_GENERATORS = (
    "stable diffusion",
    "midjourney",
    "dall-e",
    "dall·e",
    "adobe firefly",
    "comfyui",
    "automatic1111",
    "novelai",
    "leonardo.ai",
    "gpt-image",
    "imagen",
    "flux.1",
)
_XMP_SOURCE_TYPE = re.compile(r"digitalsourcetype[^<>]{0,200}", re.IGNORECASE)
_MAX_SCAN = 4 * 1024 * 1024
MAX_SIGNALS = 12


@dataclass
class SyntheticSignals:
    verdict: str = "no_declaration"  # declared_synthetic | no_declaration
    signals: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "signals": self.signals[:MAX_SIGNALS],
            "method": "declared-metadata-v1",
            "is_detector": False,
            "absence_proves_nothing": True,
            "note": (
                "Declared by file metadata or by a C2PA signer; not a pixel analysis and not proof. "
                "Absence of a declaration says nothing about how the image was made."
            ),
        }


def _png_text_chunks(data: bytes) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return out
    pos = 8
    while pos + 8 <= len(data) and len(out) < 64:
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        if ctype == b"tEXt" and b"\x00" in body:
            key, _, text = body.partition(b"\x00")
            out.append((key.decode("latin-1", "replace"), text.decode("latin-1", "replace")))
        elif ctype == b"iTXt":
            key, _, rest = body.partition(b"\x00")
            if len(rest) >= 2 and rest[0] == 0:  # uncompressed only
                parts = rest[2:].split(b"\x00", 2)
                if len(parts) == 3:
                    out.append((key.decode("utf-8", "replace"), parts[2].decode("utf-8", "replace")))
        elif ctype == b"IEND":
            break
        pos += 12 + length
    return out


def _jpeg_xmp(data: bytes) -> str:
    if not data.startswith(b"\xff\xd8"):
        return ""
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            break
        marker = data[pos + 1]
        if marker in (0xD9, 0xDA):
            break
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        seg = data[pos + 4 : pos + 2 + length]
        if marker == 0xE1 and seg.startswith(b"http://ns.adobe.com/xmp/1.0/\x00"):
            return seg.split(b"\x00", 1)[1].decode("utf-8", "replace")
        pos += 2 + length
    return ""


def _is_ai_source(text: str) -> bool:
    low = text.lower()
    return any(t in low for t in _AI_SOURCE_TYPES)


def extract_synthetic_signals(data: bytes, c2pa_ai_generated: bool = False) -> SyntheticSignals:
    """Collect declarations from the raw file bytes (and the already-parsed C2PA flag)."""
    found: list[dict[str, str]] = []
    head = data[:_MAX_SCAN]

    if c2pa_ai_generated:
        found.append({"kind": "c2pa_digital_source_type", "detail": "the C2PA manifest declares generative-AI media"})

    xmp = ""
    if head.startswith(b"\xff\xd8"):
        xmp = _jpeg_xmp(head)
    texts = _png_text_chunks(head)
    for key, value in texts:
        if key.lower() == "xml:com.adobe.xmp":
            xmp = value
    for m in _XMP_SOURCE_TYPE.finditer(xmp):
        if _is_ai_source(m.group(0)):
            found.append(
                {"kind": "xmp_digital_source_type", "detail": "XMP DigitalSourceType names generative-AI media"}
            )
            break

    for key, value in texts:
        k = key.lower()
        if k in _PNG_PARAM_KEYS:
            found.append(
                {"kind": "png_generator_chunk", "detail": f"PNG text chunk {k!r} written by a local generator"}
            )
        elif k in ("software", "comment", "description", "source"):
            low = value.lower()
            hit = next((g for g in _GENERATORS if g in low), None)
            if hit:
                found.append({"kind": "generator_name", "detail": f"PNG {k!r} text names {hit!r}"})

    if xmp:
        low = xmp.lower()
        hit = next((g for g in _GENERATORS if g in low), None)
        if hit:
            found.append({"kind": "generator_name", "detail": f"XMP names {hit!r}"})

    seen: set[tuple[str, str]] = set()
    unique = []
    for s in found:
        key2 = (s["kind"], s["detail"])
        if key2 not in seen:
            seen.add(key2)
            unique.append(s)
    return SyntheticSignals(verdict="declared_synthetic" if unique else "no_declaration", signals=unique)
