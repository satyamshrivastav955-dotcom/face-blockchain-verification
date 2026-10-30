"""
Geometric verification of image derivatives (SIFT + RANSAC homography).

Uses deterministic, richly textured synthetic images (smooth blobs have no local
features). The point of the feature is to recover derivatives that a 64-bit pHash
misses - crops, rotations, mirrored copies - without accepting unrelated images.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from src.config import SOCIAL_DOMAINS
from src.search import Candidate
from src.verification.candidate_matcher import (
    ConfirmationStatus as S,
    claim_for,
    classify,
    confirm_candidates,
    limitations_for,
)
from src.verification.geometry import MIN_INLIERS, GeometricMatcher
from src.vision.face_detector import Face
from src.vision.preprocess import phash

from conftest import write_png


def textured(seed: int, n: int = 300, size: int = 400) -> np.ndarray:
    rng = np.random.default_rng(seed)
    im = np.full((size, size, 3), 128, np.uint8)
    cv2.setRNGSeed(seed)
    cv2.randu(im, (60, 60, 60), (190, 190, 190))
    im = cv2.GaussianBlur(im, (0, 0), 2)
    for _ in range(n):
        colour = tuple(int(x) for x in rng.integers(0, 255, 3))
        p = tuple(int(v) for v in rng.integers(0, size, 2))
        q = tuple(int(v) for v in rng.integers(0, size, 2))
        kind = int(rng.integers(0, 3))
        if kind == 0:
            cv2.circle(im, p, int(rng.integers(4, 30)), colour, -1)
        elif kind == 1:
            cv2.rectangle(im, p, q, colour, -1)
        else:
            cv2.line(im, p, q, colour, int(rng.integers(1, 5)))
    return im


def rotate(im, degrees):
    h, w = im.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
    return cv2.warpAffine(im, m, (w, h), borderMode=cv2.BORDER_REPLICATE)


def jpeg(im, quality):
    ok, buf = cv2.imencode(".jpg", im, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


A = textured(1)
UNRELATED = [textured(2), textured(3), textured(4)]


@pytest.fixture(scope="module")
def matcher():
    return GeometricMatcher(A)


class TestDerivativesAreRecovered:
    @pytest.mark.parametrize(
        "name,make",
        [
            ("identical", lambda: A),
            ("resize 50%", lambda: cv2.resize(A, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)),
            ("crop 60%", lambda: A[80:320, 60:300]),
            ("crop 40%", lambda: A[100:260, 100:260]),
            ("rotate 20 deg", lambda: rotate(A, 20)),
            ("jpeg q15", lambda: jpeg(A, 15)),
            ("blur sigma 3", lambda: cv2.GaussianBlur(A, (0, 0), 3)),
            ("overlay bar", lambda: np.where(np.arange(400)[None, :, None] < 150, 255, A).astype(np.uint8)),
        ],
    )
    def test_accepted(self, matcher, name, make):
        result = matcher.match(make())
        assert result.passed, f"{name}: {result}"
        assert result.inliers >= MIN_INLIERS and result.inlier_ratio >= 0.3

    def test_mirrored_copy_is_found_and_flagged(self, matcher):
        result = matcher.match(cv2.flip(A, 1))
        assert result.passed and result.mirrored

    def test_crop_defeats_phash_but_not_geometry(self, matcher):
        crop = A[100:260, 100:260]
        from src.vision.preprocess import hamming

        assert hamming(phash(A), phash(crop)) > 12  # the gap this feature closes
        assert matcher.match(crop).passed


class TestUnrelatedImagesAreRejected:
    @pytest.mark.parametrize("other", UNRELATED)
    def test_textured_unrelated(self, matcher, other):
        result = matcher.match(other)
        assert not result.passed
        assert result.inliers < MIN_INLIERS // 2  # a wide margin, not a near miss

    def test_noise_and_blank_images(self, matcher):
        noise = np.random.default_rng(0).integers(0, 255, (400, 400, 3), dtype=np.uint8)
        assert not matcher.match(noise).passed
        assert not matcher.match(np.full((400, 400, 3), 90, np.uint8)).passed

    def test_a_featureless_query_is_unusable_and_never_matches(self):
        blank = GeometricMatcher(np.full((300, 300, 3), 128, np.uint8))
        assert not blank.usable
        assert not blank.match(A).passed

    def test_tiny_candidate(self, matcher):
        assert not matcher.match(np.zeros((8, 8, 3), np.uint8)).passed


class TestPolicy:
    def test_geometric_pass_gives_a_derivative_never_a_face_match(self):
        status = classify(
            face_similarity=0.0,
            embeddable_faces=1,
            phash_distance=40,
            cosine_threshold=0.363,
            phash_max_distance=12,
            geometric_passed=True,
        )
        assert status == S.IMAGE_DERIVATIVE

    def test_face_match_still_outranks_geometry(self):
        status = classify(
            face_similarity=0.9,
            embeddable_faces=1,
            phash_distance=40,
            cosine_threshold=0.363,
            phash_max_distance=12,
            geometric_passed=True,
        )
        assert status == S.FACE_MATCH

    def test_no_geometry_means_the_old_behaviour(self):
        assert (
            classify(
                face_similarity=0.0,
                embeddable_faces=1,
                phash_distance=40,
                cosine_threshold=0.363,
                phash_max_distance=12,
            )
            == S.LOW_SIMILARITY
        )

    def test_claim_and_limitations_name_the_basis(self):
        geo = claim_for(S.IMAGE_DERIVATIVE, "geometric")
        assert "geometric transform" in geo and "did NOT independently confirm" in geo
        assert "perceptual-hash" in claim_for(S.IMAGE_DERIVATIVE, "phash")
        assert any("repeated textures" in x for x in limitations_for(S.IMAGE_DERIVATIVE, "geometric"))
        assert not any("repeated textures" in x for x in limitations_for(S.IMAGE_DERIVATIVE, "phash"))


class ScriptedEngine:
    name = "scripted"

    def analyze(self, img):
        v = np.zeros(128, np.float32)
        v[1] = 1.0  # orthogonal to the query embedding: the face test must fail
        return [Face(bbox=(0, 0, 10, 10), det_score=0.9, landmarks=[(0, 0)] * 5, embedding=v)]


def test_confirm_candidates_recovers_a_cropped_copy(tmp_path):
    q = np.zeros(128, np.float32)
    q[0] = 1.0
    crop = write_png(tmp_path / "crop.png", A[100:260, 100:260])
    unrelated = write_png(tmp_path / "other.png", UNRELATED[0])
    results = confirm_candidates(
        query_embedding=q,
        query_phash=phash(A),
        query_image=A,
        candidates=[
            Candidate(page_url="https://x.com/a/1", image_url=str(crop), position=1),
            Candidate(page_url="https://example.org/b", image_url=str(unrelated), position=2),
        ],
        engine=ScriptedEngine(),
        cosine_threshold=0.363,
        phash_max_distance=12,
        social_domains=SOCIAL_DOMAINS,
        allow_local_files=True,
    )
    hit, miss = results
    assert hit.status == S.IMAGE_DERIVATIVE and hit.derivative_basis == "geometric"
    assert hit.geo_inliers >= MIN_INLIERS and not hit.face_check_passed
    assert miss.status == S.LOW_SIMILARITY and miss.derivative_basis == ""
    row = hit.to_json()
    assert row["derivative_basis"] == "geometric" and row["geo_inliers"] == hit.geo_inliers


def test_without_a_query_image_behaviour_is_unchanged(tmp_path):
    q = np.zeros(128, np.float32)
    q[0] = 1.0
    crop = write_png(tmp_path / "crop.png", A[100:260, 100:260])
    (hit,) = confirm_candidates(
        query_embedding=q,
        query_phash=phash(A),
        candidates=[Candidate(page_url="https://x.com/a/1", image_url=str(crop))],
        engine=ScriptedEngine(),
        cosine_threshold=0.363,
        phash_max_distance=12,
        social_domains=SOCIAL_DOMAINS,
        allow_local_files=True,
    )
    assert hit.status == S.LOW_SIMILARITY
