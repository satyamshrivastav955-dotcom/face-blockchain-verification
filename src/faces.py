"""Backward-compatibility shim — real code lives in src.vision.face_detector."""
from .vision.face_detector import *  # noqa: F401,F403
from .vision.face_detector import __all__  # noqa: F811
from .vision.face_detector import best_similarity  # noqa: F401 - not in __all__ but used
