"""Backward-compatibility shim — real code lives in src.blockchain.client."""
from .blockchain.client import *  # noqa: F401,F403
from .blockchain.client import __all__  # noqa: F811
from .blockchain.client import (  # noqa: F401 - not in __all__ but used by tests
    CONTRACT_SOURCE,
    BUILD_DIR,
    SOLC_VERSION,
    CONTRACT_NAME,
    ARTIFACT_PATH,
)
