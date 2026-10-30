#!/usr/bin/env python3
"""
Download the InsightFace ONNX models used by the ``arcface-*`` engines.

    python scripts/fetch_insightface.py [--only buffalo_l|antelopev2]

LICENCE: these weights are published by the InsightFace project for NON-COMMERCIAL
RESEARCH use only. Fetching them means you accept that. They are written to
``models/insightface/`` (git-ignored) and must not be committed or redistributed.

Integrity: the official GitHub release assets publish no checksum, so the pins
below are SHA-256 values *computed from the artifacts downloaded from the official
release URLs* on 2026-10-30 (trust-on-first-use). They detect later corruption or
substitution of a file you already trust; they do not independently prove the
release asset was authentic. Downloads are atomic and verified before use.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "models" / "insightface"
BASE = "https://github.com/deepinsight/insightface/releases/download/v0.7/{name}.zip"

# zip-member -> (output file, sha256 of the extracted file, size)
PACKS = {
    "buffalo_l": {
        "det_10g.onnx": ("det_10g.onnx", "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91", 16923827),
        "w600k_r50.onnx": (
            "w600k_r50.onnx",
            "4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43",
            174383860,
        ),
    },
    "antelopev2": {
        "antelopev2/glintr100.onnx": (
            "glintr100.onnx",
            "4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf",
            260665334,
        ),
    },
}


def _ok(path: Path, sha: str, size: int) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest() == sha


def fetch(pack: str) -> bool:
    import requests

    members = PACKS[pack]
    if all(_ok(DEST / out, sha, size) for out, sha, size in members.values()):
        print(f"{pack}: already present and verified")
        return True
    DEST.mkdir(parents=True, exist_ok=True)
    url = BASE.format(name=pack)
    print(f"{pack}: GET {url}")
    tmp = ""
    try:
        with requests.get(url, stream=True, timeout=(10, 300)) as resp:
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as fh:
                tmp = fh.name
                done = 0
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    print(f"\r    {done / 1e6:7.1f} MB", end="", flush=True)
        print()
        with zipfile.ZipFile(tmp) as zf:
            for member, (out, sha, size) in members.items():
                data = zf.read(member)
                if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
                    raise ValueError(f"{out} does not match the pinned checksum")
                part = DEST / (out + ".part")
                part.write_bytes(data)
                os.replace(part, DEST / out)  # atomic
                print(f"    ok  {out}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  failed: {type(exc).__name__}: {str(exc)[:160]}")
        return False
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
        for p in DEST.glob("*.part"):
            p.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", choices=sorted(PACKS))
    args = parser.parse_args()
    print("NOTE: InsightFace weights are for non-commercial research use only.\n")
    ok = all(fetch(p) for p in ([args.only] if args.only else PACKS))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
