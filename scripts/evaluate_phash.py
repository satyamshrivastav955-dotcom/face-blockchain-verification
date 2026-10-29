#!/usr/bin/env python3
"""
Reproducible evaluation of the perceptual-hash (image-derivative) test.

WHAT THIS MEASURES - AND WHAT IT DOES NOT
=========================================
It measures how the pHash Hamming-distance rule (``PHASH_MAX_DISTANCE``) behaves
on **synthetic** images under common transformations. It uses no photographs and
no faces, so it says nothing about face matching, about real photographs, or
about any population. The synthetic images are smooth random fields: real photos
have different frequency statistics, so treat the numbers as a sanity check of
the mechanism, not as a performance claim.

The FACE-MATCH side (YuNet + SFace, cosine threshold) is NOT evaluated here: doing
so honestly needs a licensed, consented face dataset with identity labels, and the
repository ships none. See docs/EVALUATION.md.

Usage:
    python scripts/evaluate_phash.py [--threshold 12] [--images 40] [--json out.json]

Deterministic: fixed seeds, no network.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.vision.preprocess import hamming, phash  # noqa: E402


def synthetic_image(seed: int, size: int = 256) -> np.ndarray:
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32) / size
    field = 0.25 + 0.2 * (rng.random() * xs + rng.random() * ys)
    for _ in range(int(rng.integers(3, 7))):
        cx, cy = rng.random(2)
        sigma = 0.08 + 0.2 * rng.random()
        amp = (rng.random() - 0.5) * 0.9
        field += amp * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma**2)))
    gray = np.clip(field, 0.02, 0.98)
    colour = np.stack([gray * (0.8 + 0.4 * rng.random()) for _ in range(3)], axis=-1)
    return (np.clip(colour, 0, 1) * 255).astype(np.uint8)


def jpeg(img: np.ndarray, quality: int) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return np.asarray(cv2.imdecode(buf, cv2.IMREAD_COLOR))


def crop(img: np.ndarray, frac: float) -> np.ndarray:
    h, w = img.shape[:2]
    ch, cw = int(h * frac), int(w * frac)
    y, x = (h - ch) // 2, (w - cw) // 2
    return img[y : y + ch, x : x + cw]


def rotate(img: np.ndarray, degrees: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
    return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REPLICATE)


TRANSFORMS = {
    "resize 50%": lambda im: cv2.resize(im, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA),
    "resize 25%": lambda im: cv2.resize(im, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA),
    "jpeg q80": lambda im: jpeg(im, 80),
    "jpeg q50": lambda im: jpeg(im, 50),
    "jpeg q20": lambda im: jpeg(im, 20),
    "blur sigma 1.5": lambda im: cv2.GaussianBlur(im, (0, 0), 1.5),
    "blur sigma 4": lambda im: cv2.GaussianBlur(im, (0, 0), 4),
    "brightness +30": lambda im: np.clip(im.astype(np.int32) + 30, 0, 255).astype(np.uint8),
    "centre crop 90%": lambda im: crop(im, 0.9),
    "centre crop 70%": lambda im: crop(im, 0.7),
    "rotate 5 deg": lambda im: rotate(im, 5),
    "horizontal flip": lambda im: cv2.flip(im, 1),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--threshold", type=int, default=12)
    parser.add_argument("--images", type=int, default=40)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    started = time.perf_counter()
    originals = [synthetic_image(seed) for seed in range(args.images)]
    hashes = [phash(im) for im in originals]

    rows = {}
    for name, fn in TRANSFORMS.items():
        distances = [hamming(h, phash(fn(im))) for im, h in zip(originals, hashes, strict=True)]
        rows[name] = {
            "pairs": len(distances),
            "min": min(distances),
            "median": statistics.median(distances),
            "max": max(distances),
            "true_accepts": sum(d <= args.threshold for d in distances),
            "false_rejects": sum(d > args.threshold for d in distances),
        }

    negatives = [hamming(hashes[i], hashes[j]) for i in range(len(hashes)) for j in range(i + 1, len(hashes))]
    negative = {
        "pairs": len(negatives),
        "min": min(negatives),
        "median": statistics.median(negatives),
        "max": max(negatives),
        "false_accepts": sum(d <= args.threshold for d in negatives),
        "true_rejects": sum(d > args.threshold for d in negatives),
    }
    elapsed = time.perf_counter() - started

    result = {
        "threshold": args.threshold,
        "images": args.images,
        "synthetic_only": True,
        "environment": {
            "python": platform.python_version(),
            "opencv": cv2.__version__,
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "elapsed_seconds": round(elapsed, 3),
        "transform_pairs": rows,
        "unrelated_pairs": negative,
    }

    print(
        f"pHash evaluation - SYNTHETIC images only, threshold {args.threshold}/64, {args.images} images, {elapsed:.2f}s"
    )
    print(f"opencv {cv2.__version__}, numpy {np.__version__}, python {platform.python_version()}\n")
    print(f"{'transformation':<18}{'pairs':>6}{'min':>5}{'med':>6}{'max':>5}{'TA':>5}{'FR':>5}")
    for name, r in rows.items():
        print(
            f"{name:<18}{r['pairs']:>6}{r['min']:>5}{r['median']:>6}{r['max']:>5}"
            f"{r['true_accepts']:>5}{r['false_rejects']:>5}"
        )
    n = negative
    print(
        f"\nunrelated pairs: {n['pairs']}  distance min/median/max = "
        f"{n['min']}/{n['median']}/{n['max']}  false accepts {n['false_accepts']}  "
        f"true rejects {n['true_rejects']}"
    )
    print(
        "\nTA = true accept, FR = false reject (same image, transformed). Synthetic data: "
        "no conclusion about real photographs or faces."
    )
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
