"""Anchoring backends other than the EVM registry (see docs/DECISIONS.md D1)."""

from .ots import (
    DEFAULT_CALENDARS,
    DEFAULT_EXPLORERS,
    OtsCheck,
    OtsError,
    check_ots_anchor,
    submit_digest,
    upgrade_anchor,
)

__all__ = [
    "DEFAULT_CALENDARS",
    "DEFAULT_EXPLORERS",
    "OtsCheck",
    "OtsError",
    "check_ots_anchor",
    "submit_digest",
    "upgrade_anchor",
]
