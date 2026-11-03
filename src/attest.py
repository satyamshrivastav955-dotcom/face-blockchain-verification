"""
Image-only attestation: the privacy-first core of FaceProof.

``attest`` produces a signed, optionally Bitcoin-timestamped record about a FILE. It never detects,
embeds or compares a face, never searches, and (unless you opt in to a timestamp) never touches the
network. What it records:

* the file's SHA-256 (exact-copy binding), size and pixel dimensions;
* a 64-bit perceptual hash (near-copy comparison; NOT an identity measure);
* the C2PA Content Credentials state (read-only; absence proves nothing);
* declared synthetic-media signals (metadata only; see src/signals/synthetic.py).

The claim it supports is deliberately small: "a file with this SHA-256 existed, and was attested by
this key, no later than this anchor". It does not say who made the image, that it is genuine, or who
appears in it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import ATTESTATION_SCHEMA, __version__
from .config import ConfigError, Settings
from .evidence.hashing import sha256_file
from .evidence.record import save_record, seal, utc_now
from .signals import extract_synthetic_signals
from .ui import Console
from .verification.c2pa_check import inspect_content_credentials
from .vision.preprocess import image_info, load_image, phash

__all__ = ["build_attestation_payload", "run_attest", "CLAIM", "LIMITATIONS"]

EXIT_OK = 0
EXIT_ERROR = 1

CLAIM = (
    "A file with the SHA-256 below existed when this record was created and was described as stated. "
    "Anchored records additionally show the record hash existed by the anchor time."
)
LIMITATIONS = [
    "No face was detected, embedded or compared; this record says nothing about who or what is depicted.",
    "A signature proves a key signed the record, not who holds the key or that the description is true.",
    "An anchor proves the record hash existed by a time, not that the image was created then.",
    "Declared synthetic-media signals come from metadata; absence of a declaration proves nothing.",
    "A perceptual hash finds visually similar images; it is not proof of identical origin.",
]


def build_attestation_payload(
    image_path: str | Path,
    *,
    note: str = "",
    created_at: str | None = None,
    trust_anchors_pem: str | None = None,
) -> dict[str, Any]:
    """Assemble the hashed payload for *image_path*. Local only; reads the file, writes nothing."""
    path = Path(image_path)
    data = path.read_bytes()
    image = load_image(path)
    info = image_info(image)
    credentials = inspect_content_credentials(data, trust_anchors_pem=trust_anchors_pem)
    signals = extract_synthetic_signals(data, c2pa_ai_generated=credentials.ai_generated)
    payload: dict[str, Any] = {
        "schema": ATTESTATION_SCHEMA,
        "created_at": created_at or utc_now(),
        "tool": {"name": "faceproof", "version": __version__},
        "source_image": {
            "sha256": sha256_file(path),
            "bytes": len(data),
            "width": info["width"],
            "height": info["height"],
            "phash": f"{phash(image):016x}",
            "content_credentials": credentials.to_json(),
        },
        "synthetic_media_signals": signals.to_json(),
        "claim": CLAIM,
        "limitations": LIMITATIONS,
    }
    if note:
        payload["note"] = note[:500]
    return payload


def run_attest(
    settings: Settings,
    image_path: str | Path,
    *,
    sign: bool = False,
    anchor_backend: str = "none",
    consent_timestamp_calendars: bool = False,
    note: str = "",
    output: str | Path | None = None,
    console: Console | None = None,
) -> int:
    ui = console or Console()
    path = Path(image_path)
    ui.header("Image provenance  -  ATTEST (image only: no face analysis, no search)")

    if anchor_backend not in ("none", "ots"):
        raise ConfigError(f"unknown anchor backend {anchor_backend!r} (expected none or ots)")
    if anchor_backend == "ots" and not consent_timestamp_calendars:
        ui.fail("a timestamp needs third-party calendar servers; pass --consent-timestamp-calendars")
        ui.info("what would be sent: the 32-byte record hash only - never the image, a face or a URL")
        ui.info("nothing has been sent")
        return EXIT_ERROR

    private_key = None
    if sign:
        from .trust import load_private_key

        if not settings.signing_key_file:
            ui.fail("--sign needs a key: set SIGNING_KEY_FILE or run 'keygen --out <path>' first")
            return EXIT_ERROR
        private_key = load_private_key(settings.signing_key_file)

    ui.step("Reading and describing the file (local)")
    anchors = (
        Path(settings.c2pa_trust_anchors_file).read_text(encoding="utf-8") if settings.c2pa_trust_anchors_file else None
    )
    payload = build_attestation_payload(path, note=note, trust_anchors_pem=anchors)
    src = payload["source_image"]
    ui.ok(f"{path.name}  {src['width']}x{src['height']}  {src['bytes']:,} bytes")
    ui.field("sha256", src["sha256"])
    ui.field("pHash", src["phash"])
    ui.field("C2PA", f"{src['content_credentials']['state']} (absence proves nothing)")
    ui.field("synthetic-media declarations", payload["synthetic_media_signals"]["verdict"])

    record = seal(payload)
    vhash = record["integrity"]["verification_hash"]
    ui.field("verification hash", vhash)

    if private_key is not None:
        from .trust import sign_record

        sign_record(record, private_key)
        ui.ok(f"signed with key {record['signature']['key_id']} (Ed25519)")
    else:
        ui.warn("unsigned: anyone could have made this record. Use --sign for an author.")

    if anchor_backend == "ots":
        from .anchors import DEFAULT_CALENDARS, OtsError, submit_digest

        calendars = [c.strip() for c in settings.ots_calendars.split(",") if c.strip()] or list(DEFAULT_CALENDARS)
        ui.step("Timestamping with OpenTimestamps (sends only the record hash)")
        try:
            record["anchor"] = submit_digest(vhash, calendars)
        except OtsError as exc:
            ui.fail(str(exc))
            return EXIT_ERROR
        ui.ok(f"accepted by {len(record['anchor']['calendars'])} calendar(s); status: pending")
        ui.info("Bitcoin confirmation takes hours. Run 'ots-upgrade --record <file>' later.")
    else:
        ui.info("not anchored: no time evidence. Add --anchor ots for an OpenTimestamps proof.")

    out = Path(output) if output else (settings.output_dir / "attestation.json")
    save_record(record, out)
    ui.step("Done")
    ui.field("record", str(out))
    ui.out()
    ui.out(f"  Verify it with:  python -m src.main verify --record {out} --image {path}")
    return EXIT_OK
