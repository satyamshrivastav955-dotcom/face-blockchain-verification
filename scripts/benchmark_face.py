#!/usr/bin/env python3
"""
Face-verification benchmark on LFW (Labeled Faces in the Wild), with stress tests.

    python scripts/fetch_lfw.py                       # once; public research dataset
    python scripts/benchmark_face.py --engines opencv,arcface-r50,arcface-r100 --json out.json

PROTOCOL
========
Standard LFW "image-restricted" 10-fold protocol: 6000 pairs (3000 same / 3000
different identity) from ``pairs.txt``, folds of 600. For each engine, every image
goes through the **full production path** (detect -> align -> embed) - raw, unaligned
LFW images, not the pre-cropped benchmark crops - and the pair score is the cosine
similarity of the largest face in each image.

* A pair where either image yields no embeddable face is a *failure to enroll*
  (FTE). It is scored as -1 (forced reject) and counted; it is never dropped.
* Accuracy: 10-fold cross-validation, threshold fit on 9 folds and tested on the
  held-out one (mean +/- std over folds).
* ROC metrics (AUC, EER, TAR at FAR 1e-2 and 1e-3) use all pairs. With 3000
  negatives, FAR=1e-3 means 3 false accepts: treat it as indicative, not precise.
* Stress tests degrade the *second* image of the first ``--stress-pairs`` pairs
  (balanced) and re-score at the threshold fixed from the clean run, reporting
  accuracy and FTE per condition.

WHAT THIS CAN AND CANNOT SHOW
=============================
LFW is saturated: strong models score > 99%, so clean accuracy barely separates
them, and it is not demographically balanced. The stress tests and the FAR-based
numbers are the more informative part. This is a verification benchmark, not an
identification or population-fairness study, and says nothing about IJB-C, CFP-FP
or AgeDB. Timings are for this machine only (see the printed environment).
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

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- data


def load_pairs(data_home: Path) -> list[tuple[Path, Path, int, int]]:
    """[(img_a, img_b, same(1/0), fold)] from LFW pairs.txt."""
    lfw = data_home / "lfw_home" / "lfw"
    lines = (data_home / "lfw_home" / "pairs.txt").read_text().split("\n")
    folds, per = (int(x) for x in lines[0].split())
    rows = [ln.split("\t") for ln in lines[1:] if ln.strip()]
    pairs = []
    idx = 0
    for fold in range(folds):
        for _ in range(per):
            n, a, b = rows[idx]
            idx += 1
            pairs.append((lfw / n / f"{n}_{int(a):04d}.jpg", lfw / n / f"{n}_{int(b):04d}.jpg", 1, fold))
        for _ in range(per):
            n1, a, n2, b = rows[idx]
            idx += 1
            pairs.append((lfw / n1 / f"{n1}_{int(a):04d}.jpg", lfw / n2 / f"{n2}_{int(b):04d}.jpg", 0, fold))
    return pairs


def read(path: Path) -> np.ndarray:
    return np.asarray(cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR))


# ----------------------------------------------------------------------- degradations


def d_downscale(im):  # a small face in a big frame
    h, w = im.shape[:2]
    small = cv2.resize(im, (max(24, w // 5), max(24, h // 5)), interpolation=cv2.INTER_AREA)
    return small


def d_jpeg(im):
    ok, buf = cv2.imencode(".jpg", im, [int(cv2.IMWRITE_JPEG_QUALITY), 12])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def d_blur(im):
    return cv2.GaussianBlur(im, (0, 0), 3.0)


def d_lowlight(im):
    return np.clip(im.astype(np.float32) * 0.3, 0, 255).astype(np.uint8)


def d_mask(im):  # lower-face occlusion (mask-like band)
    out = im.copy()
    h, w = out.shape[:2]
    out[int(h * 0.55) : int(h * 0.85), int(w * 0.25) : int(w * 0.75)] = (200, 200, 200)
    return out


def d_rotate(im):
    h, w = im.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 30, 1.0)
    return cv2.warpAffine(im, m, (w, h), borderMode=cv2.BORDER_REPLICATE)


STRESS = {
    "downscale 5x": d_downscale,
    "jpeg q12": d_jpeg,
    "blur sigma 3": d_blur,
    "low light x0.3": d_lowlight,
    "lower-face occlusion": d_mask,
    "rotate 30 deg": d_rotate,
}

# ------------------------------------------------------------------------------ metrics


def best_threshold(scores: np.ndarray, labels: np.ndarray) -> float:
    cand = np.unique(np.concatenate([scores, [scores.min() - 1e-6]]))
    accs = [((scores >= t) == labels).mean() for t in cand]
    return float(cand[int(np.argmax(accs))])


def roc_metrics(scores: np.ndarray, labels: np.ndarray) -> dict:
    pos, neg = scores[labels == 1], scores[labels == 0]
    order = np.argsort(-scores)
    lab = labels[order]
    tp = np.cumsum(lab)
    fp = np.cumsum(1 - lab)
    tpr, fpr = tp / max(1, len(pos)), fp / max(1, len(neg))
    auc = float(np.trapezoid(tpr, fpr))
    fnr = 1 - tpr
    eer_i = int(np.argmin(np.abs(fnr - fpr)))
    out = {"auc": auc, "eer": float((fnr[eer_i] + fpr[eer_i]) / 2)}
    for far in (1e-2, 1e-3):
        thr = float(
            np.sort(neg)[::-1][max(0, int(np.floor(far * len(neg))) - 1)] if far * len(neg) >= 1 else neg.max() + 1e-6
        )
        # threshold such that FAR <= far
        thr = float(np.quantile(neg, 1 - far, method="higher")) + 1e-9
        out[f"threshold_at_far_{far:g}"] = thr
        out[f"tar_at_far_{far:g}"] = float((pos >= thr).mean())
    return out


def cv_accuracy(scores: np.ndarray, labels: np.ndarray, folds: np.ndarray) -> tuple[float, float]:
    accs = []
    for f in np.unique(folds):
        tr, te = folds != f, folds == f
        t = best_threshold(scores[tr], labels[tr])
        accs.append(float(((scores[te] >= t) == labels[te]).mean()))
    return float(np.mean(accs)), float(np.std(accs))


# -------------------------------------------------------------------------------- engine


def make_engine(name: str, models: Path, provider: str):
    if name == "opencv":
        from src.vision.face_detector import OpenCVFaceEngine

        return OpenCVFaceEngine(models)
    from src.vision.onnx_engine import OnnxFaceEngine

    prov = ["CPUExecutionProvider"] if provider == "cpu" else ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return OnnxFaceEngine(models, name, providers=prov)


RULES = ("largest", "center", "prominence")


def all_faces(engine, img):
    """Embeddable faces with the image shape, so every selection rule can be applied to one inference."""
    return [f for f in engine.analyze(img) if f.embedding is not None], img.shape


def choose(faces_shape, rule):
    from src.vision.face_detector import select_primary

    faces, shape = faces_shape
    if not faces:
        return None
    if rule == "largest":
        return max(faces, key=lambda f: f.area).embedding
    if rule == "center":
        h, w = shape[:2]
        return min(
            faces, key=lambda f: (f.bbox[0] + f.bbox[2] / 2 - w / 2) ** 2 + (f.bbox[1] + f.bbox[3] / 2 - h / 2) ** 2
        ).embedding
    primary, _ = select_primary(faces, shape)
    return primary.embedding if primary is not None else None


def primary_embedding(engine, img, rule="prominence"):
    return choose(all_faces(engine, img), rule)


def cosine(a, b) -> float:
    if a is None or b is None:
        return -1.0
    a, b = a.astype(np.float64).ravel(), b.astype(np.float64).ravel()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--engines", default="opencv,arcface-r50,arcface-r100")
    ap.add_argument("--data-home", default=str(ROOT / "eval_data"))
    ap.add_argument("--provider", choices=("cpu", "cuda"), default="cuda")
    ap.add_argument("--max-pairs", type=int, default=0, help="debug: use only the first N pairs")
    ap.add_argument("--stress-pairs", type=int, default=600)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    pairs = load_pairs(Path(args.data_home))
    if args.max_pairs:
        pairs = pairs[:: max(1, len(pairs) // args.max_pairs)]  # stride keeps every fold and both classes
    labels = np.array([p[2] for p in pairs])
    folds = np.array([p[3] for p in pairs])
    # balanced stress subset: first N same + first N different
    half = args.stress_pairs // 2
    same_idx = [i for i, p in enumerate(pairs) if p[2] == 1][:half]
    diff_idx = [i for i, p in enumerate(pairs) if p[2] == 0][:half]
    stress_idx = same_idx + diff_idx

    import cv2 as _cv

    env = {
        "python": platform.python_version(),
        "opencv": _cv.__version__,
        "platform": platform.platform(),
        "processor": platform.processor()[:60],
    }
    try:
        import onnxruntime as ort

        env["onnxruntime"] = ort.__version__
        env["ort_providers"] = ort.get_available_providers()
    except ImportError:
        pass
    results: dict = {
        "protocol": (
            "LFW 10-fold, raw images, full detect-align-embed path; "
            "headline numbers use the production prominence face-selection rule"
        ),
        "pairs": len(pairs),
        "environment": env,
        "engines": {},
    }

    models = ROOT / "models"
    for name in args.engines.split(","):
        engine = make_engine(name, models, args.provider)
        print(f"\n=== {name} ===", flush=True)
        t0 = time.perf_counter()
        cache: dict[Path, tuple] = {}

        def faces_of(path: Path):  # noqa: B023 - called within the same iteration
            if path not in cache:  # noqa: B023
                cache[path] = all_faces(engine, read(path))  # noqa: B023
            return cache[path]  # noqa: B023

        scores_by_rule = {r: np.empty(len(pairs)) for r in RULES}
        fte_pairs = 0
        for i, (a, b, _, _) in enumerate(pairs):
            fa, fb = faces_of(a), faces_of(b)
            for r in RULES:
                scores_by_rule[r][i] = cosine(choose(fa, r), choose(fb, r))
            fte_pairs += int(not fa[0] or not fb[0])
            if i % 1000 == 0:
                print(f"  {i}/{len(pairs)}", flush=True)
        elapsed = time.perf_counter() - t0
        scores = scores_by_rule["prominence"]
        acc_mean, acc_std = cv_accuracy(scores, labels, folds)
        metrics = roc_metrics(scores, labels)
        thr_clean = best_threshold(scores, labels)
        enrolled_imgs = sum(bool(v[0]) for v in cache.values())
        multi = sum(len(v[0]) > 1 for v in cache.values())
        by_rule = {}
        for r in RULES:
            m_, s_ = cv_accuracy(scores_by_rule[r], labels, folds)
            rm = roc_metrics(scores_by_rule[r], labels)
            by_rule[r] = {"accuracy_10fold_mean": m_, "accuracy_10fold_std": s_, "auc": rm["auc"], "eer": rm["eer"]}
        entry = {
            "accuracy_10fold_mean": acc_mean,
            "accuracy_10fold_std": acc_std,
            "best_threshold_all_pairs": thr_clean,
            "pairs_with_enrollment_failure": fte_pairs,
            "images": len(cache),
            "images_without_face": len(cache) - enrolled_imgs,
            "images_with_multiple_faces": multi,
            "failure_to_enroll_rate_images": (len(cache) - enrolled_imgs) / len(cache),
            "wall_seconds_total": elapsed,
            "selection_rule_comparison": by_rule,
            **metrics,
        }

        # stress tests at the clean-fit threshold
        stress = {}
        for cname, fn in STRESS.items():
            correct = fte = 0
            for i in stress_idx:
                a, b, y, _ = pairs[i]
                ea = choose(faces_of(a), "prominence")
                eb = primary_embedding(engine, fn(read(b)))
                s = cosine(ea, eb)
                fte += int(eb is None)
                correct += int((s >= thr_clean) == bool(y))
            stress[cname] = {"accuracy": correct / len(stress_idx), "failure_to_enroll": fte / len(stress_idx)}
        entry["stress_at_clean_threshold"] = stress

        # timing on a representative image
        sample = read(pairs[0][0])
        big = cv2.resize(sample, (1280, 1280), interpolation=cv2.INTER_CUBIC)
        entry["timing_250px"] = engine.timing(sample, 15) if hasattr(engine, "timing") else _time(engine, sample)
        entry["timing_1280px"] = engine.timing(big, 15) if hasattr(engine, "timing") else _time(engine, big)
        entry["licence"] = getattr(engine, "model_license", "")
        results["engines"][name] = entry
        print(json.dumps({k: v for k, v in entry.items() if k != "stress_at_clean_threshold"}, indent=1, default=float))
        for k, v in stress.items():
            print(f"  stress {k:<22} acc {v['accuracy']:.3f}  FTE {v['failure_to_enroll']:.3f}")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, default=float), encoding="utf-8")
    return 0


def _time(engine, img, repeats=15):
    engine.analyze(img)
    ts = []
    for _ in range(repeats):
        t = time.perf_counter()
        engine.analyze(img)
        ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    return {"p50_ms": statistics.median(ts), "p95_ms": ts[int(len(ts) * 0.95)], "provider": "cpu (OpenCV DNN)"}


if __name__ == "__main__":
    sys.exit(main())
