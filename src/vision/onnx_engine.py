"""
High-accuracy face engines on ONNX Runtime: SCRFD detection + ArcFace embedding.

WHY THIS EXISTS
===============
The original engine (OpenCV YuNet + SFace, 2021-2023 vintage) is small and easy
to ship, but it is not what a current system would use for accuracy. This module
adds the generation that modern pipelines are built on:

* **Detection: SCRFD-10G with 5-point landmarks** (Guo et al., "Sample and
  Computation Redistribution for Efficient Face Detection"), run multi-scale
  on a letterboxed input, decoded and NMS'd here.
* **Embedding: ArcFace-family ResNets** (additive angular margin loss, Deng et
  al.), 512-d, on a 112x112 similarity-aligned crop, optionally with horizontal-
  flip test-time augmentation. Two checkpoints are supported:
  ``arcface-r50`` (ResNet-50, WebFace600K) and ``arcface-r100`` (ResNet-100,
  Glint360K).

The decode/alignment code follows the published reference behaviour so the
published models give their published embeddings.

LICENCE - READ BEFORE ANY COMMERCIAL USE
========================================
The InsightFace pretrained weights (``det_10g.onnx``, ``w600k_r50.onnx``,
``glintr100.onnx``) are distributed by the InsightFace project **for non-
commercial research use only**, and were trained on face datasets whose own
terms vary. That is why these engines carry ``commercial_use = False``, why the
licence is written into every record, and why the permissive ``opencv`` engine
remains available. Nothing here changes what those licences permit.

Weights are not committed to Git. ``python scripts/fetch_insightface.py``
downloads them from the official release assets.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .face_detector import Face, ModelMissingError

__all__ = [
    "OnnxFaceEngine",
    "ENGINE_SPECS",
    "EngineSpec",
    "available_engines",
    "ARCFACE_TEMPLATE_112",
    "align_face",
    "scrfd_decode",
]

# Canonical ArcFace 5-point template for a 112x112 crop (left eye, right eye, nose, left/right mouth corner).
ARCFACE_TEMPLATE_112 = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)

INSIGHTFACE_LICENSE = (
    "InsightFace pretrained weights: non-commercial research use only; "
    "training-data terms vary (see https://github.com/deepinsight/insightface)"
)


class EngineSpec:
    """Static description of one engine configuration."""

    def __init__(self, name, det, rec, embedding_dim, default_threshold, description):
        self.name = name
        self.det = det
        self.rec = rec
        self.embedding_dim = embedding_dim
        # Cosine threshold used when FACE_COSINE_THRESHOLD is not set explicitly. Chosen from
        # scripts/benchmark_face.py on LFW: the threshold giving FAR ~= 1e-3 (r50 0.221, r100 0.251
        # measured) plus a ~0.03 margin. Indicative only: 3 false accepts is the resolution of
        # 3000 negative pairs. See docs/EVALUATION.md. Override with FACE_COSINE_THRESHOLD.
        self.default_threshold = default_threshold
        self.description = description


ENGINE_SPECS: dict[str, EngineSpec] = {
    "arcface-r50": EngineSpec(
        "arcface-r50",
        "det_10g.onnx",
        "w600k_r50.onnx",
        512,
        0.25,
        "SCRFD-10G + ArcFace ResNet-50 (WebFace600K)",
    ),
    "arcface-r100": EngineSpec(
        "arcface-r100",
        "det_10g.onnx",
        "glintr100.onnx",
        512,
        0.28,
        "SCRFD-10G + ArcFace ResNet-100 (Glint360K)",
    ),
}

MODEL_SUBDIR = "insightface"


def available_engines(models_dir: str | Path) -> list[str]:
    base = Path(models_dir) / MODEL_SUBDIR
    return [n for n, s in ENGINE_SPECS.items() if (base / s.det).is_file() and (base / s.rec).is_file()]


# ---------------------------------------------------------------------------
# SCRFD decode
# ---------------------------------------------------------------------------


def _distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    return np.stack(
        [
            points[:, 0] - distance[:, 0],
            points[:, 1] - distance[:, 1],
            points[:, 0] + distance[:, 2],
            points[:, 1] + distance[:, 3],
        ],
        axis=-1,
    )


def _distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    out = []
    for i in range(0, distance.shape[1], 2):
        out.append(points[:, i % 2] + distance[:, i])
        out.append(points[:, i % 2 + 1] + distance[:, i + 1])
    return np.stack(out, axis=-1)


def _nms(dets: np.ndarray, thresh: float) -> list[int]:
    x1, y1, x2, y2, scores = (dets[:, i] for i in range(5))
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(iou <= thresh)[0] + 1]
    return keep


def scrfd_decode(
    outputs: list[np.ndarray],
    input_hw: tuple[int, int],
    det_scale: float,
    thresh: float,
    nms_thresh: float,
    strides: tuple[int, ...] = (8, 16, 32),
    num_anchors: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    """Decode SCRFD's 9 output tensors into boxes (N,5: x1,y1,x2,y2,score) and 5-point landmarks (N,5,2)."""
    fmc = len(strides)
    h, w = input_hw
    scores_l, bboxes_l, kpss_l = [], [], []
    for idx, stride in enumerate(strides):
        scores = outputs[idx].reshape(-1)
        bbox_preds = outputs[idx + fmc].reshape(-1, 4) * stride
        kps_preds = outputs[idx + fmc * 2].reshape(-1, 10) * stride
        gh, gw = h // stride, w // stride
        grid = np.mgrid[:gh, :gw]
        centers = np.stack([grid[1], grid[0]], axis=-1).astype(np.float32).reshape(-1, 2) * stride
        if num_anchors > 1:
            centers = np.stack([centers] * num_anchors, axis=1).reshape(-1, 2)
        keep = np.where(scores >= thresh)[0]
        if keep.size == 0:
            continue
        scores_l.append(scores[keep])
        bboxes_l.append(_distance2bbox(centers, bbox_preds)[keep])
        kpss_l.append(_distance2kps(centers, kps_preds).reshape(-1, 5, 2)[keep])
    if not scores_l:
        return np.zeros((0, 5), np.float32), np.zeros((0, 5, 2), np.float32)
    scores = np.concatenate(scores_l)
    bboxes = np.concatenate(bboxes_l) / det_scale
    kpss = np.concatenate(kpss_l) / det_scale
    dets = np.hstack([bboxes, scores[:, None]]).astype(np.float32)
    kept = _nms(dets, nms_thresh)
    return dets[kept], kpss[kept].astype(np.float32)


# ---------------------------------------------------------------------------
# alignment
# ---------------------------------------------------------------------------


def _umeyama(src: np.ndarray, dst: np.ndarray) -> np.ndarray | None:
    """Least-squares similarity transform (rotation, uniform scale, translation) src -> dst, as a 2x3 matrix.

    Closed form (Umeyama 1991). This is the same estimator the ArcFace reference alignment uses;
    a robust estimator (RANSAC/LMEDS) on only five points can discard valid landmarks.
    """
    src, dst = src.astype(np.float64), dst.astype(np.float64)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    sc, dc = src - mu_s, dst - mu_d
    var = (sc**2).sum() / len(src)
    if var < 1e-9:
        return None
    u, d, vt = np.linalg.svd(dc.T @ sc / len(src))
    sign = np.ones(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[-1] = -1
    rot = u @ np.diag(sign) @ vt
    scale = (d * sign).sum() / var
    t = mu_d - scale * rot @ mu_s
    matrix = np.hstack([scale * rot, t[:, None]])
    return matrix if np.isfinite(matrix).all() else None


def align_face(img: np.ndarray, landmarks: np.ndarray, size: int = 112) -> np.ndarray | None:
    """Similarity-transform *img* so its 5 landmarks sit on the ArcFace template; None if degenerate."""
    template = ARCFACE_TEMPLATE_112 * (size / 112.0)
    matrix = _umeyama(landmarks, template)
    if matrix is None:
        return None
    return cv2.warpAffine(img, matrix, (size, size), borderValue=0.0)


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class OnnxFaceEngine:
    """SCRFD + ArcFace via ONNX Runtime. Same ``analyze`` contract as the other engines."""

    commercial_use = False
    model_license = INSIGHTFACE_LICENSE

    def __init__(
        self,
        models_dir: str | Path,
        spec_name: str = "arcface-r50",
        *,
        providers: list[str] | None = None,
        det_size: tuple[int, int] = (640, 640),
        det_thresh: float = 0.5,
        nms_thresh: float = 0.4,
        flip_tta: bool = True,
        min_face_px: int = 12,
        fallback_thresh: float = 0.25,
    ) -> None:
        if spec_name not in ENGINE_SPECS:
            raise ModelMissingError(f"unknown engine {spec_name!r}; choose from {', '.join(ENGINE_SPECS)}")
        self.spec = ENGINE_SPECS[spec_name]
        self.name = f"onnx-{self.spec.name}"
        self.embedding_dim = self.spec.embedding_dim
        self.default_threshold = self.spec.default_threshold
        self.models_dir = Path(models_dir) / MODEL_SUBDIR
        self.det_size = det_size
        self.det_thresh = det_thresh
        self.fallback_thresh = fallback_thresh
        self.nms_thresh = nms_thresh
        self.flip_tta = flip_tta
        self.min_face_px = min_face_px
        self._providers_req = providers
        self._det: Any = None
        self._rec: Any = None
        self._det_in = ""
        self._rec_in = ""

    # -- loading -------------------------------------------------------------

    def _path(self, filename: str) -> Path:
        p = self.models_dir / filename
        if not p.is_file():
            raise ModelMissingError(
                f"missing model {filename} in {self.models_dir}. Run: python scripts/fetch_insightface.py"
            )
        return p

    def _session(self, path: Path):
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover
            raise ModelMissingError("onnxruntime is not installed (pip install onnxruntime)") from exc
        # ORT >= 1.21 can locate CUDA/cuDNN DLLs shipped by other installed packages
        # (e.g. PyTorch); without this the CUDA provider silently falls back to CPU.
        preload = getattr(ort, "preload_dlls", None)
        if preload is not None:
            try:
                preload()
            except Exception:  # noqa: BLE001 - optional acceleration only
                pass
        available = ort.get_available_providers()
        wanted = self._providers_req or ["CUDAExecutionProvider", "CPUExecutionProvider"]
        providers = [p for p in wanted if p in available] or ["CPUExecutionProvider"]
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        return ort.InferenceSession(str(path), sess_options=opts, providers=providers)

    @property
    def detector(self):
        if self._det is None:
            self._det = self._session(self._path(self.spec.det))
            self._det_in = self._det.get_inputs()[0].name
        return self._det

    @property
    def recognizer(self):
        if self._rec is None:
            self._rec = self._session(self._path(self.spec.rec))
            self._rec_in = self._rec.get_inputs()[0].name
        return self._rec

    @property
    def active_provider(self) -> str:
        return self.recognizer.get_providers()[0]

    def model_versions(self) -> dict[str, str]:
        return {
            "engine": self.spec.name,
            "detector": self.spec.det,
            "recognizer": self.spec.rec,
            "detector_sha256": _sha256(self._path(self.spec.det)),
            "recognizer_sha256": _sha256(self._path(self.spec.rec)),
            "licence": self.model_license,
        }

    # -- inference -----------------------------------------------------------

    def detect(self, img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Boxes (N,5) and landmarks (N,5,2) in the original image's pixel coordinates."""
        in_h, in_w = self.det_size[1], self.det_size[0]
        h, w = img.shape[:2]
        ratio_img, ratio_net = h / w, in_h / in_w
        if ratio_img > ratio_net:
            new_h, new_w = in_h, int(in_h / ratio_img)
        else:
            new_w, new_h = in_w, int(in_w * ratio_img)
        scale = new_h / h
        canvas = np.zeros((in_h, in_w, 3), np.uint8)
        canvas[:new_h, :new_w] = cv2.resize(img, (new_w, new_h))
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128, (in_w, in_h), (127.5, 127.5, 127.5), swapRB=True)
        outputs = self.detector.run(None, {self._det_in: blob})
        dets, kpss = scrfd_decode(outputs, (in_h, in_w), scale, self.det_thresh, self.nms_thresh)
        if len(dets) == 0 and self.fallback_thresh < self.det_thresh:
            # Nothing at the normal threshold: decode the SAME network outputs again, more permissively.
            # Costs no extra inference, only recovers hard faces; detections keep their (lower) scores.
            dets, kpss = scrfd_decode(outputs, (in_h, in_w), scale, self.fallback_thresh, self.nms_thresh)
        return dets, kpss

    def embed_aligned(self, aligned_bgr: np.ndarray) -> np.ndarray:
        """L2-normalised 512-d embedding of a 112x112 aligned BGR crop (with flip TTA if enabled)."""
        batch = [aligned_bgr] + ([cv2.flip(aligned_bgr, 1)] if self.flip_tta else [])
        blob = cv2.dnn.blobFromImages(batch, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        feats = self.recognizer.run(None, {self._rec_in: blob})[0].astype(np.float64)
        vec = feats.sum(axis=0) if self.flip_tta else feats[0]
        norm = np.linalg.norm(vec)
        return (vec / norm if norm > 0 else vec).astype(np.float32)

    def analyze(self, img: np.ndarray) -> list[Face]:
        """Detect every face and embed each; largest face first."""
        if img is None or img.size == 0:
            return []
        dets, kpss = self.detect(img)
        faces: list[Face] = []
        for det, kps in zip(dets, kpss, strict=True):
            x1, y1, x2, y2 = (float(v) for v in det[:4])
            bw, bh = x2 - x1, y2 - y1
            if bw < self.min_face_px or bh < self.min_face_px:
                continue
            h, w = img.shape[:2]
            face = Face(
                bbox=(int(max(0, x1)), int(max(0, y1)), int(min(bw, w)), int(min(bh, h))),
                det_score=float(det[4]),
                landmarks=[(int(round(px)), int(round(py))) for px, py in kps],
            )
            aligned = align_face(img, kps)
            if aligned is not None:
                face.aligned = aligned
                face.embedding = self.embed_aligned(aligned)
            faces.append(face)
        faces.sort(key=lambda f: f.area, reverse=True)
        return faces

    def primary(self, img: np.ndarray) -> Face:
        from .face_detector import NoFaceError

        usable = [f for f in self.analyze(img) if f.embedding is not None]
        if not usable:
            raise NoFaceError("no embeddable face detected")
        return usable[0]

    def timing(self, img: np.ndarray, repeats: int = 20) -> dict[str, Any]:
        """Median/p95 wall time of ``analyze`` on *img* (after one warm-up), for benchmarks."""
        self.analyze(img)
        ts = []
        for _ in range(repeats):
            t = time.perf_counter()
            self.analyze(img)
            ts.append((time.perf_counter() - t) * 1000)
        ts.sort()
        return {
            "p50_ms": ts[len(ts) // 2],
            "p95_ms": ts[min(len(ts) - 1, int(len(ts) * 0.95))],
            "provider": self.active_provider,
        }
