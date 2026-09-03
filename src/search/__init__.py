"""Reverse-image-search provider registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    Candidate,
    ReverseSearchProvider,
    SearchError,
    SearchResult,
    domain_of,
    is_social,
    rank_candidates,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Settings

__all__ = [
    "Candidate",
    "ReverseSearchProvider",
    "SearchError",
    "SearchResult",
    "domain_of",
    "is_social",
    "rank_candidates",
    "PROVIDERS",
    "build_provider",
]

PROVIDERS = ("serpapi_lens", "tineye", "local_fixture")


def build_provider(name: str, settings: "Settings") -> ReverseSearchProvider:
    """Instantiate a provider by name.

    Imports are deferred into each branch so that a missing optional key or an
    unrelated import error in one backend cannot stop the others from working.
    """
    key = (name or "").strip().lower()

    if key in ("serpapi_lens", "serpapi", "lens", "google_lens"):
        from .serpapi_lens import SerpApiLensProvider

        return SerpApiLensProvider(settings.serpapi_key)

    if key == "tineye":
        from .tineye import TinEyeProvider

        return TinEyeProvider(settings.tineye_api_key)

    if key in ("local_fixture", "fixture", "offline"):
        from .local_fixture import LocalFixtureProvider

        return LocalFixtureProvider(settings.fixture_path)

    raise SearchError(
        f"unknown search provider {name!r}. Available: {', '.join(PROVIDERS)}"
    )
