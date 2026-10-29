#!/usr/bin/env python3
"""
Download the YuNet and SFace ONNX models from the official OpenCV Zoo.

Run once after installing requirements:

    python scripts/fetch_models.py

Integrity
=========
Each file is verified against a pinned SHA-256 *and* size. The pins are the
``oid sha256:`` / ``size`` values from the git-lfs pointer files in
https://github.com/opencv/opencv_zoo (branch ``main``) - i.e. the repository's
own statement of what the blob must be - and equal the files this script has
downloaded. They are not guessed. A download that does not match is deleted and
reported; it is never kept. If OpenCV Zoo ever replaces a model, this script
fails loudly instead of silently accepting different weights, and the pins must
be re-derived from the new pointer file.

Downloads are written to a temporary file in the models directory and moved into
place only after verification (atomic on the same filesystem); the temporary
file is removed on any failure, including Ctrl-C.

The weights are NOT committed to Git (see .gitignore). Licences, as stated in the
OpenCV Zoo model directories (checked 2026-10-29): YuNet - MIT; SFace - Apache-2.0.
Keep those licence texts with any redistribution.

THE GIT-LFS TRAP
================
OpenCV Zoo stores weights with git-lfs. Fetching an LFS file from
``raw.githubusercontent.com`` returns a ~130-byte *pointer file* with HTTP 200.
We request ``media.githubusercontent.com`` first (which resolves LFS), fall back
to the raw host, and the checksum rejects a pointer file in any case.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

LFS_POINTER_PREFIX = b"version https://git-lfs"

MODELS: list[dict[str, Any]] = [
    {
        "filename": "face_detection_yunet_2023mar.onnx",
        "repo_path": "models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "purpose": "face detection (YuNet)",
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "size": 232589,
    },
    {
        "filename": "face_recognition_sface_2021dec.onnx",
        "repo_path": "models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "purpose": "face embedding (SFace)",
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        "size": 38696353,
    },
]

MIRRORS = [
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/{repo_path}",
    "https://raw.githubusercontent.com/opencv/opencv_zoo/main/{repo_path}",
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify(path: Path, spec: dict) -> None:
    """Raise ``ValueError`` unless *path* is exactly the pinned artifact."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        if fh.read(64).startswith(LFS_POINTER_PREFIX):
            raise ValueError("received a git-lfs pointer file instead of the model weights")
    if size != spec["size"]:
        raise ValueError(f"size {size} != expected {spec['size']}")
    digest = sha256_of(path)
    if digest != spec["sha256"]:
        raise ValueError(f"sha256 {digest[:16]}... != expected {spec['sha256'][:16]}...")


def download(url: str, dest: Path, spec: dict) -> None:
    """Fetch *url* to a temp file, verify it, then move it to *dest* atomically."""
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    try:
        with requests.get(url, stream=True, timeout=(10, 120)) as resp:
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, dir=dest.parent, suffix=".part") as tmp:
                tmp_name = tmp.name
                done = 0
                for chunk in resp.iter_content(1024 * 256):
                    if not chunk:
                        continue
                    done += len(chunk)
                    if done > spec["size"] + 1024:
                        raise ValueError("response is larger than the expected model")
                    tmp.write(chunk)
                    print(f"\r    {done / 1e6:6.2f} MB", end="", flush=True)
        print()
        verify(Path(tmp_name), spec)
        os.replace(tmp_name, dest)  # atomic on the same filesystem
        tmp_name = ""
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)


def main() -> int:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    for spec in MODELS:
        dest = MODELS_DIR / spec["filename"]
        print(f"\n{spec['filename']}  ({spec['purpose']}, {spec['size'] / 1e6:.2f} MB)")

        if dest.exists():
            try:
                verify(dest, spec)
                print("  already present and verified")
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"  existing file failed verification ({exc}); re-downloading")
                dest.unlink(missing_ok=True)

        last_error: Exception | None = None
        for template in MIRRORS:
            url = template.format(repo_path=spec["repo_path"])
            print(f"  GET {url}")
            try:
                download(url, dest, spec)
                print("  ok, checksum verified")
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  failed: {type(exc).__name__}: {str(exc)[:160]}")
                last_error = exc

        if last_error is not None:
            failures.append(spec["filename"])

    if failures:
        print("\nCould not fetch: " + ", ".join(failures))
        print(
            "Download them manually from https://github.com/opencv/opencv_zoo "
            "(use the 'Download raw file' button so git-lfs resolves) and place "
            f"them in {MODELS_DIR}; this script verifies them on the next run."
        )
        return 1

    print("\nVerifying the models load in OpenCV...")
    try:
        import cv2

        cv2.FaceDetectorYN.create(str(MODELS_DIR / MODELS[0]["filename"]), "", (320, 320))
        cv2.FaceRecognizerSF.create(str(MODELS_DIR / MODELS[1]["filename"]), "")
        print("Both models loaded. Face stack is ready.")
    except Exception as exc:  # noqa: BLE001
        print(f"Models downloaded but OpenCV could not load them: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
