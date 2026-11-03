"""
Tamper-detection demonstration for image-only attestations: six forgeries, each verified for real.

Nothing is simulated except the *forger*: every scenario builds a real record with the real code, damages it
the way an attacker would, and runs the real verifier. The table printed at the end is the verifier's own
verdict per scenario, and the command's exit code is 0 only if every forgery was rejected.

Run with a throwaway key generated in a temp directory, no network and no chain.
"""

from __future__ import annotations

import copy
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2

from .attest import build_attestation_payload
from .config import Settings
from .evidence.record import save_record, seal
from .pipeline import run_verify
from .trust import generate_key, load_private_key, sign_record
from .ui import Console
from .vision.preprocess import hamming, load_image, phash


@dataclass
class Scenario:
    name: str
    what: str
    verdict: str  # REJECTED | ACCEPTED-AS-CONSISTENT | CONTROL
    failed_check: str
    detail: str
    ok: bool  # the verifier behaved as it should


def _quiet_verify(settings: Settings, record: Path, **kw: Any) -> dict[str, Any]:
    report: dict[str, Any] = {}
    run_verify(settings, record, console=Console(stream=_Null(), force_ascii=True), report=report, **kw)
    return report


class _Null:
    def write(self, _s: str) -> int:
        return 0

    def flush(self) -> None:
        pass


def _first_fail(report: dict[str, Any]) -> tuple[str, str]:
    for name, c in report["checks"].items():
        if c["status"] == "fail":
            return name, c["detail"]
    return "", ""


def run_attestation_tamper_suite(settings: Settings, image_path: Path, ui: Console) -> int:
    ui.header("Tamper demonstration  -  image-only attestation, six forgeries")
    scenarios: list[Scenario] = []
    with tempfile.TemporaryDirectory(prefix="faceproof-tamper-") as tmp:
        tmpdir = Path(tmp)
        genuine_pub = generate_key(tmpdir / "author.pem")
        attacker_pub = generate_key(tmpdir / "attacker.pem")
        author, attacker = load_private_key(tmpdir / "author.pem"), load_private_key(tmpdir / "attacker.pem")

        payload = build_attestation_payload(image_path)
        genuine = sign_record(seal(payload), author)
        ui.field("image sha256", payload["source_image"]["sha256"])
        ui.field("author key", genuine["signature"]["key_id"])
        ui.field("attacker key", attacker_pub[:16])
        ui.info("an unanchored record is used so the demo needs no network; the anchor is tested separately")

        def verify(rec: dict[str, Any], name: str, **kw: Any) -> dict[str, Any]:
            return _quiet_verify(settings, save_record(rec, tmpdir / f"{name}.json"), **kw)

        # 0. control
        rep = verify(genuine, "genuine", image_path=image_path, trusted_keys=[genuine_pub])
        ok = all(rep["checks"][k]["status"] == "pass" for k in ("local_integrity", "signature", "image_binding"))
        scenarios.append(
            Scenario(
                "control",
                "untouched record, right image, pinned author key",
                "CONTROL",
                "",
                "hash, signature and image all pass",
                ok,
            )
        )

        # 1. naive edit
        rec = copy.deepcopy(genuine)
        rec["payload"]["note"] = "an attacker added this"
        rep = verify(rec, "naive", image_path=image_path)
        name, detail = _first_fail(rep)
        scenarios.append(
            Scenario(
                "1 naive edit", "payload changed, hash left alone", "REJECTED", name, detail, name == "local_integrity"
            )
        )

        # 2. re-sealed edit, old signature
        forged_payload = copy.deepcopy(payload)
        forged_payload["source_image"]["sha256"] = "0" * 64
        rec = seal(forged_payload)
        rec["signature"] = genuine["signature"]
        rep = verify(rec, "resealed", trusted_keys=[genuine_pub])
        name, detail = _first_fail(rep)
        scenarios.append(
            Scenario(
                "2 re-sealed edit",
                "payload edited, hash recomputed, author's old signature copied",
                "REJECTED",
                name,
                detail,
                name == "signature",
            )
        )

        # 3. re-sealed and re-signed by the attacker
        rec = sign_record(seal(forged_payload), attacker)
        unpinned = verify(rec, "attacker_unpinned")
        pinned = verify(rec, "attacker_pinned", trusted_keys=[genuine_pub])
        name, detail = _first_fail(pinned)
        scenarios.append(
            Scenario(
                "3 forged by another key",
                "edited, re-sealed and signed with the attacker's own key",
                "REJECTED",
                name,
                detail + " (without pinning this PASSES the signature check: it proves a key signed, not whose key)",
                name == "signature" and unpinned["checks"]["signature"]["status"] == "pass",
            )
        )

        # 4. one pixel changed in the image
        img = load_image(image_path)
        edited = img.copy()
        edited[0, 0] = (edited[0, 0].astype(int) ^ 0x01).astype("uint8")
        edited_path = tmpdir / "one_pixel.png"
        cv2.imwrite(str(edited_path), edited)
        rep = verify(genuine, "pixel", image_path=edited_path)
        name, detail = _first_fail(rep)
        scenarios.append(
            Scenario(
                "4 one pixel edited",
                "the file differs by a single bit in one pixel",
                "REJECTED",
                name,
                detail,
                name == "image_binding",
            )
        )

        # 5. re-encoded / screenshotted copy
        copy_path = tmpdir / "recompressed.jpg"
        cv2.imwrite(str(copy_path), img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        rep = verify(genuine, "recompressed", image_path=copy_path)
        name, detail = _first_fail(rep)
        dist = hamming(phash(img), phash(load_image(copy_path)))
        scenarios.append(
            Scenario(
                "5 re-encoded copy",
                "same picture saved again as JPEG q70",
                "REJECTED",
                name,
                f"{detail} (pHash distance {dist}/64: visually the same, not the attested bytes)",
                name == "image_binding",
            )
        )

        # 6. stripped signature
        rec = copy.deepcopy(genuine)
        rec.pop("signature")
        rep = verify(rec, "stripped", image_path=image_path, trusted_keys=[genuine_pub])
        name, detail = _first_fail(rep)
        scenarios.append(
            Scenario(
                "6 signature stripped",
                "signature removed from the record",
                "REJECTED",
                name,
                detail,
                name == "signature",
            )
        )

    ui.out()
    ui.rule()
    width = max(len(s.name) for s in scenarios)
    for s in scenarios:
        mark = ui.tick if s.ok else ui.cross
        tag = f"[{s.failed_check}] " if s.failed_check else ""
        ui.out(f"  {mark} {s.name:<{width}}  {s.verdict:<9} {tag}{s.detail[:110]}")
    ui.rule()
    bad = [s for s in scenarios if not s.ok]
    if bad:
        ui.fail(f"{len(bad)} scenario(s) did not behave as required")
        return 1
    ui.ok("every forgery was rejected; the control passed")
    ui.info("not shown: a back-dated claim (needs the OpenTimestamps anchor) - see docs/THREAT_MODEL.md T7")
    return 0
