"""
Face detection and embedding.

MODEL CHOICE
============
OpenCV's bundled YuNet detector and SFace recognizer are used deliberately in
preference to dlib / ``face_recognition``. Both ship inside ``opencv-python``
as ONNX graphs with no compilation step, whereas dlib requires CMake and MSVC
build tools on Windows and routinely costs hours before a single face is
detected. YuNet is ~230 KB and SFace ~37 MB, so the whole face stack downloads
in seconds.

WHAT IS AND IS NOT CLAIMED
==========================
An embedding here supports the claim "these two images contain the same face",
which is what image-provenance verification needs. It is not an identity
lookup: nothing in this project maps a face to a legal identity, and the
threshold is a similarity cut-off, not proof of personhood. See the Limitations
section of the README.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import cv2
import numpy as np

__all__ = [
    "Face",
    "FaceEngine",
    "OpenCVFaceEngine",
    "StubFaceEngine",
    "ModelMissingError",
    "NoFaceError",
    "cosine_similarity",
    "embedding_fingerprint",
    "DET_MODEL_FILE",
    "REC_MODEL_FILE",
]

DET_MODEL_FILE = "face_detection_yunet_2023mar.onnx"
REC_MODEL_FILE = "face_recognition_sface_2021dec.onnx"


class ModelMissingError(RuntimeError):
    """An ONNX model file is absent."""


class NoFaceError(RuntimeError):
    """No face was found in an image where one was required."""


@dataclass
class Face:
    """One detected face and everything derived from it."""

    bbox: tuple[int, int, int, int]  # x, y, w, h
    det_score: float
    landmarks: list[tuple[int, int]]
    embedding: np.ndarray | None = None
    aligned: np.ndarray | None = None

    @property
    def area(self) -> int:
        return int(self.bbox[2]) * int(self.bbox[3])

    def to_json(self) -> dict[str, object]:
        """Integer-only summary, safe to place in a hashed payload."""
        x, y, w, h = self.bbox
        return {
            "bbox": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
            "landmarks": [{"x": int(px), "y": int(py)} for px, py in self.landmarks],
        }


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two embeddings.

    Equivalent to ``FaceRecognizerSF.match(..., FR_COSINE)``, but implemented in
    numpy so embeddings can be compared without an initialised recognizer -
    useful in tests and when re-scoring stored vectors.
    """
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    if a.size != b.size:
        raise ValueError(f"embedding size mismatch: {a.size} vs {b.size}")
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def embedding_fingerprint(embedding: np.ndarray) -> str:
    """SHA-256 commitment to an embedding, for the record.

    The raw biometric vector is *never* published or placed on-chain. Only this
    fingerprint goes into the payload, so the record commits to which face was
    used without disclosing a template that could be matched elsewhere.

    Formatting each component to fixed precision (rather than hashing raw
    float32 bytes) keeps the value stable across platforms where the last
    mantissa bit might differ.
    """
    vec = np.asarray(embedding, dtype=np.float64).ravel()
    text = ",".join(f"{v:.6f}" for v in vec)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


class FaceEngine(Protocol):
    """Interface the pipeline depends on, so engines are swappable."""

    name: str
    embedding_dim: int

    def analyze(self, img: np.ndarray) -> list[Face]: ...


class OpenCVFaceEngine:
    """YuNet detection + SFace embedding."""

    name = "opencv-yunet+sface"

    def __init__(
        self,
        models_dir: str | Path,
        *,
        score_threshold: float = 0.9,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
    ) -> None:
        self.models_dir = Path(models_dir)
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.top_k = top_k
        self.embedding_dim = 128
        self._detector = None
        self._recognizer = None

    # -- model loading -----------------------------------------------------

    def _model_path(self, filename: str) -> Path:
        path = self.models_dir / filename
        if not path.exists():
            raise ModelMissingError(
                f"missing model {filename} in {self.models_dir}. "
                "Run:  python scripts/fetch_models.py"
            )
        # An ONNX graph is a protobuf and is never this small; a few hundred
        # bytes almost always means a git-lfs pointer file was saved instead of
        # the real weights, which otherwise fails later with a cryptic error.
        if path.stat().st_size < 50_000:
            raise ModelMissingError(
                f"{path} is only {path.stat().st_size} bytes, which is too small "
                "to be real weights - it is probably a git-lfs pointer. "
                "Delete it and re-run:  python scripts/fetch_models.py"
            )
        return path

    @property
    def detector(self):
        if self._detector is None:
            self._detector = cv2.FaceDetectorYN.create(
                str(self._model_path(DET_MODEL_FILE)),
                "",
                (320, 320),
                self.score_threshold,
                self.nms_threshold,
                self.top_k,
            )
        return self._detector

    @property
    def recognizer(self):
        if self._recognizer is None:
            self._recognizer = cv2.FaceRecognizerSF.create(
                str(self._model_path(REC_MODEL_FILE)), ""
            )
        return self._recognizer

    def model_versions(self) -> dict[str, str]:
        return {"detector": DET_MODEL_FILE, "recognizer": REC_MODEL_FILE}

    # -- inference ---------------------------------------------------------

    def analyze(self, img: np.ndarray) -> list[Face]:
        """Detect every face and compute an embedding for each.

        Returned largest-face-first: when an image holds several faces the
        biggest is nearly always the subject, and a group photo must not cause
        the pipeline to silently score against a bystander.
        """
        if img is None or img.size == 0:
            return []
        height, width = img.shape[:2]

        # YuNet requires the input size to be declared before every detect
        # call; skipping this on a differently-sized image yields garbage boxes.
        self.detector.setInputSize((int(width), int(height)))
        _, raw = self.detector.detect(img)
        if raw is None or len(raw) == 0:
            return []

        faces: list[Face] = []
        for row in raw:
            row = np.asarray(row, dtype=np.float32).ravel()
            x, y, w, h = (int(round(v)) for v in row[:4])
            # Clamp to the frame: YuNet can return boxes slightly out of bounds.
            x, y = max(0, x), max(0, y)
            w, h = max(1, min(w, width - x)), max(1, min(h, height - y))
            landmarks = [
                (int(round(row[4 + i * 2])), int(round(row[5 + i * 2]))) for i in range(5)
            ]
            face = Face(
                bbox=(x, y, w, h),
                det_score=float(row[14]) if row.size > 14 else 0.0,
                landmarks=landmarks,
            )
            try:
                aligned = self.recognizer.alignCrop(img, row)
                feature = self.recognizer.feature(aligned)
                face.aligned = aligned
                face.embedding = np.asarray(feature, dtype=np.float32).ravel()
            except cv2.error:
                # Alignment can fail on extreme edge crops; keep the detection
                # (it still counts toward face_count) but leave it unscoreable.
                pass
            faces.append(face)

        faces.sort(key=lambda f: f.area, reverse=True)
        return faces

    def primary(self, img: np.ndarray) -> Face:
        """The largest embeddable face, or raise."""
        faces = [f for f in self.analyze(img) if f.embedding is not None]
        if not faces:
            raise NoFaceError("no embeddable face detected")
        return faces[0]


class StubFaceEngine:
    """Deterministic, model-free engine for OFFLINE TESTS ONLY.

    Exists because the ONNX weights require a network download, so CI (and a
    sandbox without egress) cannot exercise the real engine. It treats the
    whole image as one face and derives a 128-d vector from a heavily
    downsampled luminance grid, which gives the one property the plumbing tests
    need: identical images score 1.0 and unrelated images score low.

    It is NOT a face detector and must never be used for a real verification;
    :func:`src.pipeline.build_engine` refuses to select it unless explicitly
    asked.
    """

    name = "stub-test-only"

    def __init__(self) -> None:
        self.embedding_dim = 128

    def model_versions(self) -> dict[str, str]:
        return {"detector": "stub", "recognizer": "stub"}

    def analyze(self, img: np.ndarray) -> list[Face]:
        if img is None or img.size == 0:
            return []
        height, width = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        grid = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
        vec = grid.astype(np.float32).ravel()  # 256
        vec = vec[0::2] + vec[1::2]  # -> 128
        vec = vec - float(vec.mean())
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return [
            Face(
                bbox=(0, 0, int(width), int(height)),
                det_score=1.0,
                landmarks=[(0, 0)] * 5,
                embedding=vec.astype(np.float32),
                aligned=cv2.resize(img, (112, 112), interpolation=cv2.INTER_AREA),
            )
        ]

    def primary(self, img: np.ndarray) -> Face:
        faces = self.analyze(img)
        if not faces:
            raise NoFaceError("no image data")
        return faces[0]


def best_similarity(
    query: np.ndarray, faces: Sequence[Face]
) -> tuple[float, Face | None]:
    """Highest cosine similarity between *query* and any face in *faces*.

    Scanning every face matters for candidate images: the subject may be one
    person in a group shot, and comparing only against the largest face would
    reject a genuine match.
    """
    best_score, best_face = -1.0, None
    for face in faces:
        if face.embedding is None:
            continue
        score = cosine_similarity(query, face.embedding)
        if score > best_score:
            best_score, best_face = score, face
    return (best_score if best_face is not None else 0.0), best_face
