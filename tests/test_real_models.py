"""
Checks that use the REAL YuNet/SFace weights when they are present in models/.

Skipped (with the reason shown) when the weights have not been downloaded, so the
suite stays hermetic. No face photographs are committed to this repository, so
these tests cover model integrity, loading, numerical behaviour and the
no-face path on synthetic images - they do NOT measure recognition accuracy.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from src.vision.face_detector import (
    DET_MODEL_FILE,
    MODEL_SHA256,
    MODEL_SIZE,
    REC_MODEL_FILE,
    OpenCVFaceEngine,
    cosine_similarity,
)

from conftest import make_blob

MODELS = Path(__file__).resolve().parent.parent / "models"
pytestmark = pytest.mark.skipif(
    not all((MODELS / f).is_file() for f in (DET_MODEL_FILE, REC_MODEL_FILE)),
    reason="model weights not downloaded (python scripts/fetch_models.py)",
)


@pytest.fixture(scope="module")
def engine():
    return OpenCVFaceEngine(MODELS)


def test_weights_match_the_pinned_official_checksums():
    for name in (DET_MODEL_FILE, REC_MODEL_FILE):
        data = (MODELS / name).read_bytes()
        assert len(data) == MODEL_SIZE[name]
        assert hashlib.sha256(data).hexdigest() == MODEL_SHA256[name]


def test_model_versions_report_the_loaded_file_hashes(engine):
    versions = engine.model_versions()
    assert versions["detector_sha256"] == MODEL_SHA256[DET_MODEL_FILE]
    assert versions["recognizer_sha256"] == MODEL_SHA256[REC_MODEL_FILE]


def test_sface_embedding_shape_and_numerical_behaviour(engine):
    """Run the real recogniser on a 112x112 input and check the vector's properties."""
    import cv2

    aligned = cv2.resize(make_blob(256), (112, 112))
    vec = np.asarray(engine.recognizer.feature(aligned), dtype=np.float32).ravel()
    assert vec.shape == (128,) and np.isfinite(vec).all()
    assert cosine_similarity(vec, vec) == pytest.approx(1.0, abs=1e-6)
    # deterministic on repeated calls
    again = np.asarray(engine.recognizer.feature(aligned), dtype=np.float32).ravel()
    assert np.allclose(vec, again, atol=1e-6)
    # a different input gives a different vector
    other = np.asarray(engine.recognizer.feature(cv2.flip(aligned, 0) // 2), dtype=np.float32).ravel()
    assert cosine_similarity(vec, other) < 1.0 - 1e-6


def test_no_face_in_a_synthetic_image(engine):
    assert engine.analyze(make_blob(256)) == []


def test_empty_and_degenerate_inputs_do_not_crash(engine):
    assert engine.analyze(np.zeros((0, 0, 3), dtype=np.uint8)) == []
    assert engine.analyze(np.zeros((8, 8, 3), dtype=np.uint8)) == []
    assert engine.analyze(None) == []


def test_register_with_real_engine_and_no_face_fails_cleanly(settings, query_image, capsys, monkeypatch):
    import src.pipeline as pipeline
    from src.ui import Console

    # real models from the repo's models/, outputs in the tmp project root
    monkeypatch.setattr(pipeline, "build_engine", lambda *a, **k: OpenCVFaceEngine(MODELS))
    code = pipeline.run_register(
        settings,
        query_image,
        provider_name="local_fixture",
        engine_name="opencv",
        allow_offline_stub=True,
        dry_run=True,
        console=Console(force_ascii=True),
    )
    assert code == pipeline.EXIT_ERROR
    assert "no face detected" in capsys.readouterr().out
