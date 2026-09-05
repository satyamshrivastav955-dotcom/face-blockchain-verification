"""Similarity metrics, re-exported for the architecture's namespace."""

from ..vision.face_detector import cosine_similarity
from ..vision.preprocess import hamming

__all__ = ["cosine_similarity", "hamming"]
