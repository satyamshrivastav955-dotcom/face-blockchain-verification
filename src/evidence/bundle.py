"""
The evidence bundle.

Every artefact the pipeline touched is written to a per-run directory so a
reviewer can audit the result without re-running anything: the raw search
response exactly as the provider returned it, the face crops that were actually
compared, the full candidate score table including rejections, the annotated
side-by-side image, and the transaction receipt.

This is the practical answer to "how do I know the match was not hardcoded".
A hardcoded URL cannot produce a raw provider response that contains it, face
crops that score above threshold, and a plausible spread of near-miss scores.

A ``manifest.json`` lists every file with its SHA-256.

WHAT THE MANIFEST CAN AND CANNOT PROVE
======================================
It detects *accidental or naive* modification: an edited file, a deleted file
or an extra file no longer matches the manifest. It does NOT prove the bundle
was never altered: whoever can edit a file can also regenerate
``manifest.json``, and the manifest itself is not anchored on-chain. What binds
the bundle to the sealed (and anchored) record is narrower: the record's
payload commits to the SHA-256 of the raw search response, of the candidate
table and of the matched image, and :func:`verify_bundle` cross-checks those
against the files. Anything not committed that way is only as trustworthy as
wherever the directory has been stored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .hashing import sha256_bytes, sha256_file
from ..vision.preprocess import encode_png

__all__ = ["EvidenceBundle", "BundleCheck", "new_run_id", "verify_bundle"]


def new_run_id(image_sha256: str = "") -> str:
    """Directory name for a run: sortable timestamp plus an image fingerprint."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{image_sha256[:8]}" if image_sha256 else stamp


class EvidenceBundle:
    """A directory of artefacts for one pipeline run.

    The directory is created on the first write, not on construction: a run that
    aborts early (no face found, provider refused, bad key) should not leave an
    empty directory behind for a reviewer to puzzle over.
    """

    def __init__(self, root: str | Path, run_id: str) -> None:
        self.dir = Path(root) / run_id
        self.run_id = run_id
        self._files: list[str] = []

    def _ensure(self) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        return self.dir

    # -- writers -----------------------------------------------------------

    def write_json(self, name: str, obj: Any) -> Path:
        path = self._ensure() / name
        path.write_text(
            json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        self._files.append(name)
        return path

    def write_bytes(self, name: str, data: bytes) -> Path:
        path = self._ensure() / name
        path.write_bytes(data)
        self._files.append(name)
        return path

    def write_text(self, name: str, text: str) -> Path:
        path = self._ensure() / name
        path.write_text(text, encoding="utf-8")
        self._files.append(name)
        return path

    def write_image(self, name: str, img: np.ndarray | None) -> Path | None:
        if img is None or getattr(img, "size", 0) == 0:
            return None
        return self.write_bytes(name, encode_png(img))

    # -- manifest ----------------------------------------------------------

    def manifest(self) -> dict[str, Any]:
        entries = []
        for name in sorted(set(self._files)):
            path = self.dir / name
            if not path.exists():
                continue
            entries.append(
                {
                    "file": name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        return {
            "run_id": self.run_id,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "file_count": len(entries),
            "files": entries,
        }

    def finalize(self) -> Path:
        """Write ``manifest.json``. Call once, last."""
        manifest = self.manifest()
        path = self._ensure() / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return path

    def digest_of(self, data: bytes) -> str:
        return sha256_bytes(data)



# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass
class BundleCheck:
    ok: bool
    problems: list[str] = field(default_factory=list)
    files_checked: int = 0

    def to_json(self) -> dict[str, Any]:
        return {"ok": self.ok, "files_checked": self.files_checked, "problems": self.problems}


def verify_bundle(directory: str | Path, record: dict[str, Any] | None = None) -> BundleCheck:
    """Check a bundle directory against its manifest and, optionally, a record.

    Reports (never raises on) malformed manifests, path-confusing file names,
    missing, modified and unlisted files, and any disagreement between the
    record's committed digests and the files they describe.
    """
    root = Path(directory)
    problems: list[str] = []
    checked = 0
    manifest_path = root / "manifest.json"
    if not root.is_dir() or not manifest_path.is_file():
        return BundleCheck(False, ["no manifest.json in the evidence directory"])
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["files"]
        if not isinstance(entries, list):
            raise TypeError("files is not a list")
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return BundleCheck(False, ["manifest.json is malformed"])

    listed: dict[str, str] = {}
    for entry in entries:
        name = entry.get("file") if isinstance(entry, dict) else None
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not _SAFE_NAME.match(name) or name == "manifest.json":
            problems.append(f"manifest lists an unsafe or invalid file name: {str(name)[:40]!r}")
            continue
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            problems.append(f"{name}: manifest digest is not a SHA-256")
            continue
        listed[name] = digest.lower()

    for name, digest in listed.items():
        path = root / name
        if path.is_symlink() or not path.is_file():
            problems.append(f"{name}: listed in the manifest but missing")
            continue
        checked += 1
        if sha256_file(path) != digest:
            problems.append(f"{name}: contents do not match the manifest (modified)")

    for path in sorted(root.iterdir()):
        if path.name != "manifest.json" and path.name not in listed:
            problems.append(f"{path.name}: present but not listed in the manifest")

    if record is not None:
        problems.extend(_cross_check(root, listed, record))
    return BundleCheck(not problems, problems, checked)


def _cross_check(root: Path, listed: dict[str, str], record: dict[str, Any]) -> list[str]:
    payload = record.get("payload") or {}
    search = payload.get("search") or {}
    match = payload.get("match") or {}
    out: list[str] = []

    def _expect(name: str, committed: Any, label: str) -> None:
        if not committed or name not in listed:
            return
        if str(committed).lower().removeprefix("0x") != listed[name]:
            out.append(f"{name} does not match the record's {label}")

    _expect("candidates.canonical.json", search.get("candidates_sha256"), "candidates_sha256")
    _expect("search_response.raw.json", search.get("raw_response_sha256"), "raw_response_sha256")
    _expect("matched_image.original", match.get("matched_image_sha256"), "matched_image_sha256")

    table_path = root / "candidates.json"
    if table_path.is_file() and "candidates.json" in listed:
        try:
            rows = json.loads(table_path.read_text(encoding="utf-8"))
            chosen = [
                r for r in rows
                if isinstance(r, dict) and r.get("page_url") == match.get("matched_url")
                and r.get("image_url") == match.get("matched_image_url")
            ]
        except ValueError:
            out.append("candidates.json is not valid JSON")
            return out
        if not chosen:
            out.append("the matched candidate is not in candidates.json")
        elif not any(
            r.get("status") == match.get("decision_rule")
            and r.get("candidate_image_sha256") == match.get("matched_image_sha256")
            for r in chosen
        ):
            out.append(
                "candidates.json disagrees with the record about the matched "
                "candidate's status or image digest"
            )
    return out
