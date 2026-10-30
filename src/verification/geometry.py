"""
Geometric verification of image derivatives (local features + RANSAC).

WHY
===
A 64-bit perceptual hash is global and brittle: a 70% crop, a mirrored copy or a
rotation defeats it (measured in docs/EVALUATION.md). The standard remedy in
image-retrieval systems is *geometric verification*: match local features
between the two images and check that the matches are consistent with one rigid
or projective transformation. A genuine derivative (crop / resize / rotate /
mirror / re-encode / mild overlay) yields many inliers to a single homography;
unrelated images yield few, scattered ones.

It also makes the evidence *explainable*: "187 of 240 matches agree with one
transform" is a statement a reviewer can inspect, unlike a distance.

METHOD
======
SIFT keypoints (grayscale, longest side <= ``MAX_SIDE``), Lowe's ratio test
(0.75), then ``cv2.findHomography`` with RANSAC. A match is accepted only if the
inlier count and inlier ratio clear their thresholds *and* the homography is
non-degenerate (the query quad maps to a plausible, convex quad). The candidate
is tried as-is and horizontally mirrored, because SIFT is not mirror-invariant.

This proves the two images share rendered content. It says nothing about faces
or identity.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

__all__ = ["GeometricMatcher", "GeoResult", "MIN_INLIERS", "MIN_INLIER_RATIO"]

MAX_SIDE = 800
MAX_FEATURES = 2000
RATIO = 0.75
RANSAC_PX = 4.0
MIN_INLIERS = 25
MIN_INLIER_RATIO = 0.30
MIN_RAW_MATCHES = 12


@dataclass
class GeoResult:
    """Result of a geometric matching attempt between the query and one candidate image.

    Attributes:
        inliers: Number of feature-match pairs consistent with the estimated homography.
        matches: Total ratio-test-passing feature pairs submitted to RANSAC.
        mirrored: True when the candidate was horizontally flipped before matching.
        passed: True when both :data:`MIN_INLIERS` and :data:`MIN_INLIER_RATIO` are met.
        reason: Human-readable one-line summary of why the attempt passed or failed.
    """

    inliers: int = 0
    matches: int = 0
    mirrored: bool = False
    passed: bool = False
    reason: str = ""

    @property
    def inlier_ratio(self) -> float:
        return self.inliers / self.matches if self.matches else 0.0


def _prep(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1.0:
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return gray


def _plausible(h_matrix: np.ndarray, size_hw: tuple[int, int]) -> bool:
    """Reject degenerate homographies: collapsed, folded or wildly distorted mappings."""
    h, w = size_hw
    quad = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32).reshape(-1, 1, 2)
    try:
        mapped = cv2.perspectiveTransform(quad, h_matrix).reshape(4, 2)
    except cv2.error:
        return False
    if not np.isfinite(mapped).all():
        return False
    area = cv2.contourArea(mapped.astype(np.float32))
    if area < 0.01 * h * w or area > 100 * h * w:
        return False
    return bool(cv2.isContourConvex(mapped.astype(np.float32)))


class GeometricMatcher:
    """Precomputes the query's features once; ``match`` then costs one candidate's extraction."""

    def __init__(self, query_bgr: np.ndarray) -> None:
        self._sift = cv2.SIFT_create(nfeatures=MAX_FEATURES)  # type: ignore[attr-defined]
        self._bf = cv2.BFMatcher(cv2.NORM_L2)
        gray = _prep(query_bgr)
        self._size = gray.shape[:2]
        self._kp, self._des = self._sift.detectAndCompute(gray, None)

    @property
    def usable(self) -> bool:
        return self._des is not None and len(self._kp) >= MIN_RAW_MATCHES

    def _try(self, kp_c, des_c) -> GeoResult:
        if des_c is None or len(kp_c) < MIN_RAW_MATCHES:
            return GeoResult(reason="too few features in candidate")
        pairs = self._bf.knnMatch(self._des, des_c, k=2)
        good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < RATIO * n.distance]
        if len(good) < MIN_RAW_MATCHES:
            return GeoResult(matches=len(good), reason="too few ratio-test matches")
        src = np.array([self._kp[m.queryIdx].pt for m in good], dtype=np.float32).reshape(-1, 1, 2)
        dst = np.array([kp_c[m.trainIdx].pt for m in good], dtype=np.float32).reshape(-1, 1, 2)
        h_matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_PX)
        if h_matrix is None or mask is None:
            return GeoResult(matches=len(good), reason="no consistent transform")
        inliers = int(mask.sum())
        result = GeoResult(inliers=inliers, matches=len(good))
        if not _plausible(h_matrix, self._size):
            result.reason = "degenerate transform"
            return result
        result.passed = inliers >= MIN_INLIERS and result.inlier_ratio >= MIN_INLIER_RATIO
        result.reason = "consistent transform" if result.passed else "below inlier thresholds"
        return result

    def match(self, candidate_bgr: np.ndarray) -> GeoResult:
        if not self.usable:
            return GeoResult(reason="query has too few features")
        gray = _prep(candidate_bgr)
        best = GeoResult(reason="no match")
        for mirrored in (False, True):
            g = cv2.flip(gray, 1) if mirrored else gray
            kp, des = self._sift.detectAndCompute(g, None)
            res = self._try(kp, des)
            res.mirrored = mirrored
            if (res.passed, res.inliers) > (best.passed, best.inliers):
                best = res
            if best.passed and best.inliers >= 3 * MIN_INLIERS:
                break  # decisive; skip the mirrored pass
        return best
