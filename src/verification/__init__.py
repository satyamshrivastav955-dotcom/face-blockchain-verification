"""Independent candidate verification and similarity scoring."""

from .candidate_matcher import (
    Confirmation,
    ConfirmationStatus,
    confirm_candidates,
    score_table,
    select_best,
)

__all__ = [
    "Confirmation",
    "ConfirmationStatus",
    "confirm_candidates",
    "score_table",
    "select_best",
]
