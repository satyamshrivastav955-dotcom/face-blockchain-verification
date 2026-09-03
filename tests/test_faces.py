"""
Face-embedding maths and engine contract.

The real YuNet/SFace models are ~37 MB of ONNX weights that have to be
downloaded, so these tests cover the parts that are ours: the similarity
metric, the privacy-preserving fingerprint, the largest-face-first contract,
and the guard that stops the test-only stub being used for a real run.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.config import ConfigError, Settings
from src.faces import (
    Face,
    ModelMissingError,
    OpenCVFaceEngine,
    StubFaceEngine,
    best_similarity,
    cosine_similarity,
    embedding_fingerprint,
)
from src.pipeline import build_engine

from conftest import make_blob, make_stripes, rewrite


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_opposite_vectors_score_minus_one(self):
        v = np.array([1.0, 0.0], dtype=np.float32)
        assert cosine_similarity(v, -v) == pytest.approx(-1.0)

    def test_orthogonal_vectors_score_zero(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_scale_invariant(self):
        a = np.array([1.0, 2.0, 3.0])
        assert cosine_similarity(a, a * 7.5) == pytest.approx(1.0)

    def test_zero_vector_is_not_a_crash(self):
        a = np.zeros(4)
        b = np.ones(4)
        assert cosine_similarity(a, b) == 0.0

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError):
            cosine_similarity(np.ones(4), np.ones(5))

    def test_accepts_2d_input(self):
        # OpenCV returns features as a (1, 128) row, not a flat vector.
        a = np.ones((1, 8), dtype=np.float32)
        b = np.ones(8, dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(1.0)


class TestEmbeddingFingerprint:
    def test_deterministic(self):
        v = np.linspace(-1, 1, 128, dtype=np.float32)
        assert embedding_fingerprint(v) == embedding_fingerprint(v.copy())

    def test_sensitive_to_change(self):
        v = np.linspace(-1, 1, 128, dtype=np.float32)
        w = v.copy()
        w[0] += 0.01
        assert embedding_fingerprint(v) != embedding_fingerprint(w)

    def test_is_a_sha256_hex_digest(self):
        digest = embedding_fingerprint(np.ones(128, dtype=np.float32))
        assert len(digest) == 64
        int(digest, 16)

    def test_does_not_leak_the_vector(self):
        """The biometric template must not be recoverable from the record."""
        v = np.linspace(-1, 1, 128, dtype=np.float32)
        digest = embedding_fingerprint(v)
        assert all(f"{value:.6f}" not in digest for value in v[:8])

    def test_stable_across_dtypes(self):
        v32 = np.linspace(-1, 1, 128, dtype=np.float32)
        assert embedding_fingerprint(v32) == embedding_fingerprint(v32.astype(np.float64))


class TestFace:
    def test_area(self):
        assert Face(bbox=(0, 0, 10, 20), det_score=1.0, landmarks=[]).area == 200

    def test_to_json_is_integer_only(self):
        face = Face(bbox=(1, 2, 3, 4), det_score=0.9, landmarks=[(5, 6), (7, 8)])
        data = face.to_json()
        assert data["bbox"] == {"x": 1, "y": 2, "w": 3, "h": 4}
        assert all(isinstance(v, int) for v in data["bbox"].values())
        assert data["landmarks"] == [{"x": 5, "y": 6}, {"x": 7, "y": 8}]

    def test_to_json_is_canonicalizable(self):
        from src.canonical import canonicalize

        face = Face(bbox=(1, 2, 3, 4), det_score=0.987654, landmarks=[(5, 6)])
        canonicalize(face.to_json())  # would raise on a stray float


class TestStubEngine:
    def test_identical_images_score_one(self):
        engine = StubFaceEngine()
        img = make_blob()
        a = engine.analyze(img)[0].embedding
        b = engine.analyze(img.copy())[0].embedding
        assert cosine_similarity(a, b) == pytest.approx(1.0, abs=1e-6)

    def test_derivative_scores_above_threshold(self):
        engine = StubFaceEngine()
        a = engine.analyze(make_blob())[0].embedding
        b = engine.analyze(rewrite(make_blob()))[0].embedding
        assert cosine_similarity(a, b) > 0.363

    def test_unrelated_images_score_below_threshold(self):
        engine = StubFaceEngine()
        a = engine.analyze(make_blob())[0].embedding
        b = engine.analyze(make_stripes())[0].embedding
        assert cosine_similarity(a, b) < 0.363

    def test_embedding_shape(self):
        face = StubFaceEngine().analyze(make_blob())[0]
        assert face.embedding.shape == (128,)
        assert face.aligned.shape == (112, 112, 3)

    def test_empty_input(self):
        assert StubFaceEngine().analyze(np.zeros((0, 0, 3), dtype=np.uint8)) == []


class TestBestSimilarity:
    def test_picks_the_highest_scoring_face(self):
        query = np.array([1.0, 0.0, 0.0])
        faces = [
            Face(bbox=(0, 0, 1, 1), det_score=1.0, landmarks=[], embedding=np.array([0.0, 1.0, 0.0])),
            Face(bbox=(0, 0, 1, 1), det_score=1.0, landmarks=[], embedding=np.array([0.9, 0.1, 0.0])),
        ]
        score, face = best_similarity(query, faces)
        assert score > 0.9
        assert face is faces[1]

    def test_scans_every_face_not_just_the_largest(self):
        """The subject may be a small face in a group shot."""
        query = np.array([1.0, 0.0])
        faces = [
            Face(bbox=(0, 0, 100, 100), det_score=1.0, landmarks=[], embedding=np.array([0.0, 1.0])),
            Face(bbox=(0, 0, 5, 5), det_score=1.0, landmarks=[], embedding=np.array([1.0, 0.0])),
        ]
        score, _ = best_similarity(query, faces)
        assert score == pytest.approx(1.0)

    def test_no_faces(self):
        score, face = best_similarity(np.ones(4), [])
        assert score == 0.0 and face is None

    def test_ignores_faces_without_embeddings(self):
        query = np.ones(2)
        faces = [Face(bbox=(0, 0, 1, 1), det_score=1.0, landmarks=[], embedding=None)]
        score, face = best_similarity(query, faces)
        assert score == 0.0 and face is None


class TestEngineSelection:
    def test_stub_requires_an_explicit_flag(self):
        """Falling back to the stub silently would fabricate a plausible record."""
        with pytest.raises(ConfigError):
            build_engine("stub", Settings(), allow_stub=False)

    def test_stub_available_when_allowed(self):
        assert isinstance(build_engine("stub", Settings(), allow_stub=True), StubFaceEngine)

    def test_default_is_opencv(self):
        assert isinstance(build_engine("", Settings()), OpenCVFaceEngine)

    def test_unknown_engine_rejected(self):
        with pytest.raises(ConfigError):
            build_engine("magic", Settings())


class TestModelGuards:
    def test_missing_model_is_explained(self, tmp_path):
        engine = OpenCVFaceEngine(tmp_path)
        with pytest.raises(ModelMissingError) as excinfo:
            _ = engine.detector
        assert "fetch_models" in str(excinfo.value)

    def test_git_lfs_pointer_is_detected(self, tmp_path):
        """A 130-byte 'model' is an LFS pointer, and fails cryptically later."""
        from src.faces import DET_MODEL_FILE

        (tmp_path / DET_MODEL_FILE).write_text(
            "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 232589\n"
        )
        engine = OpenCVFaceEngine(tmp_path)
        with pytest.raises(ModelMissingError) as excinfo:
            _ = engine.detector
        assert "lfs" in str(excinfo.value).lower()
