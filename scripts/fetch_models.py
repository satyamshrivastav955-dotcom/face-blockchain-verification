#!/usr/bin/env python3
"""
Download the YuNet and SFace ONNX models from the OpenCV Zoo.

Run once after installing requirements:

    python scripts/fetch_models.py

THE GIT-LFS TRAP
================
OpenCV Zoo stores weights with git-lfs. Fetching a git-lfs file from
``raw.githubusercontent.com`` returns a ~130-byte *pointer file* - plain text
beginning ``version https://git-lfs.github.com/spec/v1`` - rather than the
model. It downloads with HTTP 200 and the wrong content, then fails much later
inside OpenCV with an opaque parse error. We therefore request
``media.githubusercontent.com/media/...`` first (which resolves LFS), fall back
to the raw host, and validate what actually arrived before keeping it.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

LFS_POINTER_PREFIX = b"version https://git-lfs"
MIN_PLAUSIBLE_BYTES = 50_000

MODELS = [
    {
        "filename": "face_detection_yunet_2023mar.onnx",
        "repo_path": "models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "purpose": "face detection (YuNet)",
        "approx_mb": 0.23,
    },
    {
        "filename": "face_recognition_sface_2021dec.onnx",
        "repo_path": "models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "purpose": "face embedding (SFace)",
        "approx_mb": 37.0,
    },
]

MIRRORS = [
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/{repo_path}",
    "https://raw.githubusercontent.com/opencv/opencv_zoo/main/{repo_path}",
]


def _validate(path: Path) -> None:
    size = path.stat().st_size
    head = path.open("rb").read(64)
    if head.startswith(LFS_POINTER_PREFIX):
        raise ValueError(
            "received a git-lfs pointer file instead of the model weights"
        )
    if size < MIN_PLAUSIBLE_BYTES:
        raise ValueError(f"only {size} bytes - too small to be real weights")
    if head[:1] not in (b"\x08", b"\x0a", b"\x12"):
        # ONNX is protobuf; field 1 (ir_version, varint) encodes as 0x08.
        raise ValueError("does not look like an ONNX protobuf")


def download(url: str, dest: Path) -> None:
    import requests

    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, dir=dest.parent) as tmp:
            tmp_path = Path(tmp.name)
            done = 0
            for chunk in resp.iter_content(1024 * 256):
                if chunk:
                    tmp.write(chunk)
                    done += len(chunk)
                    print(f"\r    {done / 1e6:6.2f} MB", end="", flush=True)
    print()
    try:
        _validate(tmp_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    shutil.move(str(tmp_path), str(dest))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    for spec in MODELS:
        dest = MODELS_DIR / spec["filename"]
        print(f"\n{spec['filename']}  ({spec['purpose']}, ~{spec['approx_mb']} MB)")

        if dest.exists():
            try:
                _validate(dest)
                print(f"  already present, sha256={sha256_of(dest)[:16]}...")
                continue
            except Exception as exc:
                print(f"  existing file is unusable ({exc}); re-downloading")
                dest.unlink(missing_ok=True)

        last_error: Exception | None = None
        for template in MIRRORS:
            url = template.format(repo_path=spec["repo_path"])
            print(f"  GET {url}")
            try:
                download(url, dest)
                print(f"  ok, sha256={sha256_of(dest)}")
                last_error = None
                break
            except Exception as exc:
                print(f"  failed: {exc}")
                last_error = exc

        if last_error is not None:
            failures.append(spec["filename"])

    if failures:
        print("\nCould not fetch: " + ", ".join(failures))
        print(
            "Download them manually from https://github.com/opencv/opencv_zoo "
            "(use the 'Download raw file' button so git-lfs resolves) and place "
            f"them in {MODELS_DIR}"
        )
        return 1

    print("\nVerifying the models load in OpenCV...")
    try:
        import cv2

        cv2.FaceDetectorYN.create(
            str(MODELS_DIR / MODELS[0]["filename"]), "", (320, 320)
        )
        cv2.FaceRecognizerSF.create(str(MODELS_DIR / MODELS[1]["filename"]), "")
        print("Both models loaded. Face stack is ready.")
    except Exception as exc:
        print(f"Models downloaded but OpenCV could not load them: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
