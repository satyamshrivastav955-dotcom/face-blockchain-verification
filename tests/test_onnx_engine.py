"""
ArcFace/SCRFD engine: decode, alignment, thresholds and engine selection.

The pure-numpy parts (SCRFD decode, NMS, alignment) are tested against hand-built
tensors. Tests that need the InsightFace weights are skipped, with the reason shown,
when ``models/insightface/`` is absent (``python scripts/fetch_insightface.py``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.config import ConfigError, Settings
from src.pipeline import build_engine, resolve_cosine_threshold
from src.vision.face_detector import ModelMissingError, OpenCVFaceEngine, StubFaceEngine
from src.vision.onnx_engine import (
    ARCFACE_TEMPLATE_112,
    ENGINE_SPECS,
    OnnxFaceEngine,
    _nms,
    align_face,
    available_engines,
    scrfd_decode,
)

from conftest import make_blob

MODELS = Path(__file__).resolve().parent.parent / "models"


def fake_outputs(h=64, w=64, hit=None, score=0.9):
    """Nine SCRFD tensors (scores, boxes, keypoints for strides 8/16/32) with one planted detection."""
    strides, anchors = (8, 16, 32), 2
    scores, boxes, kps = [], [], []
    for stride in strides:
        n = (h // stride) * (w // stride) * anchors
        scores.append(np.zeros((n, 1), np.float32))
        boxes.append(np.zeros((n, 4), np.float32))
        kps.append(np.zeros((n, 10), np.float32))
    if hit is not None:
        si, row, col, anchor = hit
        stride = strides[si]
        idx = ((row * (w // stride)) + col) * anchors + anchor
        scores[si][idx] = score
        boxes[si][idx] = [1, 1, 2, 2]  # distances in stride units: left, top, right, bottom
        kps[si][idx] = np.tile([0.5, -0.5], 5)
    return scores + boxes + kps


class TestScrfdDecode:
    def test_no_detection(self):
        dets, kpss = scrfd_decode(fake_outputs(), (64, 64), 1.0, 0.5, 0.4)
        assert dets.shape == (0, 5) and kpss.shape == (0, 5, 2)

    def test_planted_detection_has_the_right_geometry(self):
        # stride 8, grid cell (row 2, col 3) -> anchor centre (24, 16)
        dets, kpss = scrfd_decode(fake_outputs(hit=(0, 2, 3, 0)), (64, 64), 1.0, 0.5, 0.4)
        assert dets.shape == (1, 5)
        x1, y1, x2, y2, score = dets[0]
        assert (x1, y1, x2, y2) == (24 - 8, 16 - 8, 24 + 16, 16 + 16)
        assert score == pytest.approx(0.9)
        assert kpss[0][0].tolist() == [24 + 4, 16 - 4]

    def test_coordinates_are_scaled_back_to_the_original_image(self):
        dets, kpss = scrfd_decode(fake_outputs(hit=(0, 2, 3, 0)), (64, 64), 0.5, 0.5, 0.4)
        assert dets[0][:4].tolist() == [32.0, 16.0, 80.0, 64.0]
        assert kpss[0][0].tolist() == [56.0, 24.0]

    def test_score_threshold(self):
        out = fake_outputs(hit=(1, 1, 1, 1), score=0.3)
        assert scrfd_decode(out, (64, 64), 1.0, 0.5, 0.4)[0].shape[0] == 0
        assert scrfd_decode(out, (64, 64), 1.0, 0.25, 0.4)[0].shape[0] == 1

    def test_nms_suppresses_overlapping_boxes_and_keeps_distinct_ones(self):
        dets = np.array([[0, 0, 100, 100, 0.9], [5, 5, 105, 105, 0.8], [300, 300, 400, 400, 0.7]], np.float32)
        assert _nms(dets, 0.4) == [0, 2]


class TestAlignment:
    def test_template_maps_to_itself(self):
        out = align_face(np.full((112, 112, 3), 7, np.uint8), ARCFACE_TEMPLATE_112.copy())
        assert out.shape == (112, 112, 3)

    def test_similarity_transformed_landmarks_are_normalised_back(self):
        """Rotate/scale/shift an image with a known pattern; alignment must undo it."""
        base = np.zeros((112, 112, 3), np.uint8)
        for x, y in ARCFACE_TEMPLATE_112:
            cv2.circle(base, (int(round(x)), int(round(y))), 4, (255, 255, 255), -1)
        m = cv2.getRotationMatrix2D((56, 56), 25, 1.3)
        m[:, 2] += (30, -12)
        big = cv2.warpAffine(base, m, (300, 300))
        moved = cv2.transform(ARCFACE_TEMPLATE_112.reshape(-1, 1, 2), m).reshape(-1, 2)
        aligned = align_face(big, moved.astype(np.float32))
        assert aligned is not None
        for x, y in ARCFACE_TEMPLATE_112:
            assert aligned[int(round(y)), int(round(x))].max() > 120  # landmark blobs are back in place

    def test_degenerate_landmarks_do_not_crash(self):
        same = np.tile([10.0, 10.0], (5, 1)).astype(np.float32)
        out = align_face(np.zeros((50, 50, 3), np.uint8), same)
        assert out is None or out.shape == (112, 112, 3)


class TestSelectionAndThresholds:
    def test_specs(self):
        assert set(ENGINE_SPECS) == {"arcface-r50", "arcface-r100"}
        assert all(s.embedding_dim == 512 for s in ENGINE_SPECS.values())

    def test_missing_weights_are_explained(self, tmp_path):
        engine = OnnxFaceEngine(tmp_path, "arcface-r50")
        with pytest.raises(Exception) as excinfo:
            engine.analyze(make_blob())
        assert "fetch_insightface" in str(excinfo.value)
        assert available_engines(tmp_path) == []

    def test_unknown_engine(self, tmp_path):
        with pytest.raises(ModelMissingError):
            OnnxFaceEngine(tmp_path, "arcface-r9000")
        with pytest.raises(ConfigError):
            build_engine("nonsense", Settings())

    def test_auto_falls_back_to_the_permissive_engine_when_no_weights(self, tmp_path):
        s = Settings()
        s.root = tmp_path
        assert isinstance(build_engine("auto", s), OpenCVFaceEngine)

    def test_licence_flags(self, tmp_path):
        assert OnnxFaceEngine(tmp_path).commercial_use is False
        assert "non-commercial" in OnnxFaceEngine(tmp_path).model_license
        assert OpenCVFaceEngine(tmp_path).commercial_use is True

    def test_threshold_resolution(self, tmp_path):
        s = Settings()
        # not explicit: engine default
        thr, src = resolve_cosine_threshold(s, OnnxFaceEngine(tmp_path, "arcface-r50"))
        assert (thr, src) == (ENGINE_SPECS["arcface-r50"].default_threshold, "engine_default")
        thr, src = resolve_cosine_threshold(s, OpenCVFaceEngine(tmp_path))
        assert (thr, src) == (0.363, "engine_default")
        # explicit wins over the engine default
        s.face_cosine_threshold, s.face_threshold_explicit = 0.55, True
        assert resolve_cosine_threshold(s, OnnxFaceEngine(tmp_path)) == (0.55, "explicit")

        # an engine without a default falls back to settings
        class Bare:
            pass

        assert resolve_cosine_threshold(Settings(), Bare())[1] == "settings"
        assert resolve_cosine_threshold(Settings(), StubFaceEngine())[0] == 0.363

    def test_explicit_env_is_detected(self, monkeypatch, tmp_path):
        from src.config import load_settings

        empty = tmp_path / "e.env"
        empty.write_text("", encoding="utf-8")
        monkeypatch.delenv("FACE_COSINE_THRESHOLD", raising=False)
        assert load_settings(empty).face_threshold_explicit is False
        monkeypatch.setenv("FACE_COSINE_THRESHOLD", "0.4")
        loaded = load_settings(empty)
        assert loaded.face_threshold_explicit is True and loaded.face_cosine_threshold == 0.4


have_weights = all((MODELS / "insightface" / f).is_file() for f in ("det_10g.onnx", "w600k_r50.onnx"))


@pytest.mark.skipif(not have_weights, reason="InsightFace weights absent (python scripts/fetch_insightface.py)")
class TestWithRealWeights:
    @pytest.fixture(scope="class")
    def engine(self):
        return OnnxFaceEngine(MODELS, "arcface-r50", providers=["CPUExecutionProvider"])

    def test_weights_match_the_pinned_checksums(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "fetch_insightface", MODELS.parent / "scripts" / "fetch_insightface.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for out, sha, size in {**mod.PACKS["buffalo_l"]}.values():
            data = (MODELS / "insightface" / out).read_bytes()
            assert len(data) == size and hashlib.sha256(data).hexdigest() == sha

    def test_no_face_in_a_synthetic_image(self, engine):
        assert engine.analyze(make_blob(256)) == []
        assert engine.analyze(np.zeros((0, 0, 3), np.uint8)) == []
        assert engine.analyze(None) == []

    def test_embedding_properties(self, engine):
        aligned = cv2.resize(make_blob(256), (112, 112))
        v = engine.embed_aligned(aligned)
        assert v.shape == (512,) and v.dtype == np.float32 and np.isfinite(v).all()
        assert np.linalg.norm(v) == pytest.approx(1.0, abs=1e-5)
        assert np.allclose(v, engine.embed_aligned(aligned), atol=1e-6)  # deterministic
        other = engine.embed_aligned(cv2.flip(aligned, 0) // 2)
        assert float(v @ other) < 0.999

    def test_model_versions_report_hashes_and_licence(self, engine):
        info = engine.model_versions()
        assert len(info["detector_sha256"]) == 64 and "non-commercial" in info["licence"]
