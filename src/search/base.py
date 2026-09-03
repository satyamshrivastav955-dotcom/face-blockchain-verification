"""
Reverse-image-search provider interface.

WHY AN INTERFACE
================
The assignment's hardest constraint is that the match must be genuine, which
makes the search step the pipeline's single point of failure: an expired key,
an exhausted free quota, or a provider outage on the evening of the deadline
would sink the whole demo. Hiding each service behind one small interface means
a backend can be swapped with an environment variable instead of a rewrite.

WHAT A PROVIDER MAY AND MAY NOT DO
==================================
A provider returns *candidates*. It never decides that a candidate matches.
That judgement belongs to :mod:`src.confirm`, which independently re-detects
and re-embeds the candidate image locally. Keeping retrieval and confirmation
apart is what makes the result defensible rather than an appeal to Google's
authority - and it is why no provider is permitted to return a similarity
score.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "Candidate",
    "SearchResult",
    "ReverseSearchProvider",
    "SearchError",
    "domain_of",
    "is_social",
    "rank_candidates",
]


class SearchError(RuntimeError):
    """A reverse-image search could not be completed."""


@dataclass
class Candidate:
    """One possible source page returned by a provider."""

    page_url: str          # the web page / social post
    image_url: str = ""    # direct URL of the image on that page
    title: str = ""
    source: str = ""       # provider's label for the site
    thumbnail: str = ""
    position: int = 0      # provider's own ranking, 1-based
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def domain(self) -> str:
        return domain_of(self.page_url)

    def best_image_url(self) -> str:
        """The URL to actually download, preferring full size over thumbnail.

        Thumbnails are a last resort: they are heavily downscaled, which
        degrades both face embedding and perceptual hashing.
        """
        return self.image_url or self.thumbnail


@dataclass
class SearchResult:
    """Everything one search returned, kept whole for the evidence bundle."""

    provider: str
    endpoint: str
    searched_at: str
    candidates: list[Candidate]
    raw_response: Any
    query_image_url: str = ""
    quota_note: str = ""


def domain_of(url: str) -> str:
    """Registrable-ish host for *url*, lower-cased and without ``www.``."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_social(url: str, social_domains: tuple[str, ...]) -> bool:
    """True if *url* lives on one of *social_domains* (or a subdomain)."""
    host = domain_of(url)
    return any(host == d or host.endswith("." + d) for d in social_domains)


def rank_candidates(
    candidates: list[Candidate], social_domains: tuple[str, ...]
) -> list[Candidate]:
    """Social-media pages first, provider order preserved within each group.

    The task asks for a matching *social-media post*, so those are confirmed
    first to avoid spending the download budget on stock-photo aggregators.
    Non-social pages are kept as a fallback rather than discarded, because a
    genuine match on a news site is still real provenance evidence and it is
    better to report it than to report nothing.
    """
    social = [c for c in candidates if is_social(c.page_url, social_domains)]
    other = [c for c in candidates if not is_social(c.page_url, social_domains)]
    return social + other


class ReverseSearchProvider(ABC):
    """Base class for a reverse-image-search backend."""

    #: short identifier recorded in the payload
    name: str = "abstract"
    #: True if the service needs the query image at a publicly reachable URL
    needs_public_url: bool = False
    #: True only for offline development stubs, which must never be used for a
    #: graded run
    is_offline_stub: bool = False

    @abstractmethod
    def search(
        self,
        image_path: Path,
        *,
        image_url: str = "",
        max_results: int = 25,
    ) -> SearchResult:
        """Run a reverse-image search and return candidate source pages."""

    def describe(self) -> str:
        return self.name
