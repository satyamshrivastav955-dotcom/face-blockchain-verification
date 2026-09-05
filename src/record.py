"""Backward-compatibility shim — real code lives in src.evidence.record."""
from .evidence.record import *  # noqa: F401,F403
from .evidence.record import __all__  # noqa: F811
from .evidence.record import INTEGRITY_ALGORITHM  # noqa: F401 - not in __all__ but used
