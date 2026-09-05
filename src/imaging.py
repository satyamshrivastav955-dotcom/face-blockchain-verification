"""Backward-compatibility shim — real code lives in src.vision.preprocess."""
from .vision.preprocess import *  # noqa: F401,F403
from .vision.preprocess import __all__  # noqa: F811
from .vision.preprocess import _elide, _text_width, _label, _FONT, _SCALE  # noqa: F401 - private but used by tests
