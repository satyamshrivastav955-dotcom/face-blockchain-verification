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

A ``manifest.json`` lists every file with its SHA-256, so the bundle can itself
be shown to be unmodified.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .canonical import sha256_bytes, sha256_file
from .imaging import encode_png

__all__ = ["EvidenceBundle", "new_run_id"]


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
