#!/usr/bin/env python3
"""
Labelled evaluation of FaceProof's *image-derivative* decision on real photographs.

    python scripts/fetch_lfw.py                  # once: public research dataset into eval_data/
    python scripts/evaluate_provenance.py --sources 500 --json docs/results/provenance_eval.json

THE QUESTION
============
Given a source photo S and a candidate image C, does the pipeline's derivative test
(pHash distance <= PHASH_MAX_DISTANCE  OR  SIFT+RANSAC geometric match) say "C is S, re-encoded or edited"?

LABELS (ground truth by construction, no human labelling)
=========================================================
* POSITIVE  - C is S passed through one of 12 transformations (recompress, rescale, crop, rotate, mirror,
              screenshot-like re-capture, brightness, blur...).
* NEGATIVE, unrelated   - C is a different photo of a different person.
* NEGATIVE, same person - C is a *different photo of the same person*. This is the hard negative for a
              provenance tool: same face, different picture. (It is a POSITIVE for face matching, which is
              a different question, measured by scripts/benchmark_face.py.)

WHAT THIS DOES AND DOES NOT SHOW
================================
* Real photographs (LFW: 250x250 web news photos), not synthetic fields. It replaces the synthetic-only
  evidence for the geometric verifier.
* LFW is small, face-centred, mostly frontal, and not demographically balanced. 250 px sources give SIFT few
  features. Results are NOT a statement about phone photos, memes, screenshots of text, logos or repeated
  textures, where false matches are more likely. Negatives are random LFW photos, not adversarially chosen.
* Error rates carry Wilson 95% confidence intervals. "0 false accepts in N" is reported as an upper bound
  (the rule of three: 3/N), not as zero.
* Thresholds are the project defaults; nothing here was tuned on this data.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.verification.geometry import GeometricMatcher  # noqa: E402
from src.vision.preprocess import hamming, phash  # noqa: E402


# ------------------------------------------------------------------ statistics


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    out = {"k": k, "n": n, "rate": (k / n if n else 0.0), "ci95": [round(lo, 4), round(hi, 4)]}
    if k == 0 and n:
        out["upper_bound_rule_of_three"] = round(3 / n, 4)
    return out


# ------------------------------------------------------------------ transformations


def _jpeg(img: np.ndarray, q: int) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    decoded = cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else None
    if decoded is None:
        raise RuntimeError("JPEG round trip failed")
    return decoded


def _crop(img: np.ndarray, frac: float) -> np.ndarray:
    h, w = img.shape[:2]
    ch, cw = int(h * frac), int(w * frac)
    y, x = (h - ch) // 2, (w - cw) // 2
    return img[y : y + ch, x : x + cw]


def _rotate(img: np.ndarray, deg: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REFLECT)


def _screenshot(img: np.ndarray) -> np.ndarray:
    """A re-capture: downscale, blur a little, recompress, add a UI-like border."""
    h, w = img.shape[:2]
    small = cv2.resize(img, (int(w * 0.6), int(h * 0.6)), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (3, 3), 0.8)
    small = _jpeg(small, 60)
    return cv2.copyMakeBorder(small, 12, 12, 20, 20, cv2.BORDER_CONSTANT, value=(245, 245, 245))


TRANSFORMS = {
    "identical copy": lambda i: i.copy(),
    "jpeg q50": lambda i: _jpeg(i, 50),
    "jpeg q20": lambda i: _jpeg(i, 20),
    "resize 50%": lambda i: cv2.resize(i, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA),
    "resize 25%": lambda i: cv2.resize(i, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA),
    "blur sigma 2": lambda i: cv2.GaussianBlur(i, (0, 0), 2.0),
    "brightness +30": lambda i: cv2.convertScaleAbs(i, alpha=1.0, beta=30),
    "crop 90%": lambda i: _crop(i, 0.9),
    "crop 70%": lambda i: _crop(i, 0.7),
    "rotate 10 deg": lambda i: _rotate(i, 10),
    "mirror": lambda i: cv2.flip(i, 1),
    "screenshot-like": _screenshot,
}


# ------------------------------------------------------------------ data


def index_lfw(data_home: Path) -> dict[str, list[Path]]:
    root = data_home / "lfw_home" / "lfw"
    if not root.is_dir():
        raise SystemExit(f"LFW not found at {root}; run scripts/fetch_lfw.py first")
    people: dict[str, list[Path]] = {}
    for d in sorted(root.iterdir()):
        if d.is_dir():
            imgs = sorted(d.glob("*.jpg"))
            if imgs:
                people[d.name] = imgs
    return people


def read(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"unreadable image {path}")
    return img


def decide(src: np.ndarray, src_hash: int, matcher: GeometricMatcher, cand: np.ndarray, max_dist: int) -> dict:
    d = hamming(src_hash, phash(cand))
    g = matcher.match(cand)
    return {
        "phash": d <= max_dist,
        "geo": bool(g.passed),
        "either": d <= max_dist or bool(g.passed),
        "distance": d,
        "inliers": g.inliers,
    }


# ------------------------------------------------------------------ main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-home", default=str(ROOT / "eval_data"))
    ap.add_argument("--sources", type=int, default=500, help="number of source photos")
    ap.add_argument("--seed", type=int, default=20261103)
    ap.add_argument("--phash-max", type=int, default=12)
    ap.add_argument("--json", default="", help="write the full result here")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    people = index_lfw(Path(args.data_home))
    names = sorted(people)
    multi = [n for n in names if len(people[n]) >= 2]
    t0 = time.time()

    pos = {name: {"phash": 0, "geo": 0, "either": 0, "n": 0} for name in TRANSFORMS}
    neg = {
        "unrelated": {"phash": 0, "geo": 0, "either": 0, "n": 0, "min_distance": 64, "max_inliers": 0},
        "same person, different photo": {
            "phash": 0,
            "geo": 0,
            "either": 0,
            "n": 0,
            "min_distance": 64,
            "max_inliers": 0,
        },
    }
    exact_binding_false_accepts = 0
    exact_binding_trials = 0
    import hashlib

    used: set[Path] = set()
    false_accepts: list[dict] = []
    for s in range(args.sources):
        person = rng.choice(names)
        src_path = rng.choice(people[person])
        used.add(src_path)
        src = read(src_path)
        h = phash(src)
        matcher = GeometricMatcher(src)
        src_sha = hashlib.sha256(src.tobytes()).hexdigest()

        for name, fn in TRANSFORMS.items():
            cand = fn(src)
            r = decide(src, h, matcher, cand, args.phash_max)
            pos[name]["n"] += 1
            for k in ("phash", "geo", "either"):
                pos[name][k] += int(r[k])
            if name != "identical copy":
                exact_binding_trials += 1
                exact_binding_false_accepts += int(hashlib.sha256(cand.tobytes()).hexdigest() == src_sha)

        negatives = []
        for _ in range(2):
            other = rng.choice([n for n in names if n != person])
            negatives.append(("unrelated", rng.choice(people[other])))
        if person in multi:
            mate = rng.choice([p for p in people[person] if p != src_path])
            negatives.append(("same person, different photo", mate))
        for label, p in negatives:
            r = decide(src, h, matcher, read(p), args.phash_max)
            row = neg[label]
            row["n"] += 1
            for k in ("phash", "geo", "either"):
                row[k] += int(r[k])
            if r["either"] and len(false_accepts) < 10:
                false_accepts.append(
                    {
                        "class": label,
                        "source": str(src_path.relative_to(ROOT / "eval_data")),
                        "candidate": str(p.relative_to(ROOT / "eval_data")),
                        "phash_distance": r["distance"],
                        "geometric_inliers": r["inliers"],
                    }
                )
            row["min_distance"] = min(row["min_distance"], r["distance"])
            row["max_inliers"] = max(row["max_inliers"], r["inliers"])
        if (s + 1) % 100 == 0:
            print(f"  {s + 1}/{args.sources} sources, {time.time() - t0:.0f}s", file=sys.stderr)

    result = {
        "protocol": "LFW source photos; 12 transformations as positives; unrelated and same-person photos as negatives",
        "seed": args.seed,
        "sources": args.sources,
        "phash_max_distance": args.phash_max,
        "environment": {
            "python": platform.python_version(),
            "opencv": cv2.__version__,
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "wall_seconds": round(time.time() - t0, 1),
        "positives": {
            name: {m: rate(v[m], v["n"]) for m in ("phash", "geo", "either")} | {"n": v["n"]} for name, v in pos.items()
        },
        "negatives": {
            name: {m: rate(v[m], v["n"]) for m in ("phash", "geo", "either")}
            | {
                "n": v["n"],
                "min_phash_distance_seen": v["min_distance"],
                "max_geometric_inliers_seen": v["max_inliers"],
            }
            for name, v in neg.items()
        },
        "false_accept_examples": false_accepts,
        "exact_sha256_binding": {
            "edited_copies_accepted_as_the_original": rate(exact_binding_false_accepts, exact_binding_trials),
            "note": "SHA-256 of the pixel arrays; any transformation changes it. Exact binding has no tolerance.",
        },
    }
    print(json.dumps(result, indent=2))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
