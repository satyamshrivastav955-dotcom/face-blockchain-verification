"""
SerpApi Google Lens backend.

Google Lens has by far the best coverage of social-media pages among services
with a documented API, which is why it is the default. It is reached through
SerpApi rather than scraped, so the request is authenticated, rate-limited and
auditable - the raw JSON is archived in the evidence bundle, and the account's
search count visibly increments, both of which help demonstrate the search
really happened.

Constraint: the Lens engine takes the query image as a **URL**, not an upload,
so :mod:`src.publish` must put the local file somewhere publicly reachable
first. See ``needs_public_url``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..record import utc_now
from .base import Candidate, ReverseSearchProvider, SearchError, SearchResult

ENDPOINT = "https://serpapi.com/search.json"

# SerpApi has changed which key holds visual matches over time, and the Lens
# response can carry several result blocks at once. Reading all of them in a
# fixed priority order is more durable than betting on one key name.
_RESULT_KEYS = (
    "exact_matches",
    "visual_matches",
    "image_results",
    "image_sources",
    "related_content",
)


class SerpApiLensProvider(ReverseSearchProvider):
    name = "serpapi_google_lens"
    needs_public_url = True

    def __init__(self, api_key: str, *, timeout: int = 60) -> None:
        if not api_key:
            raise SearchError(
                "SERPAPI_KEY is not set. Get a key at https://serpapi.com/manage-api-key "
                "and put it in .env"
            )
        self.api_key = api_key
        self.timeout = timeout

    def search(
        self,
        image_path: Path,
        *,
        image_url: str = "",
        max_results: int = 25,
    ) -> SearchResult:
        import requests

        if not image_url:
            raise SearchError(
                "Google Lens needs the query image at a public URL. Either set "
                "PUBLISH_PROVIDER in .env so the image is uploaded automatically, "
                "or pass --image-url with a URL you host yourself."
            )

        params = {
            "engine": "google_lens",
            "url": image_url,
            "api_key": self.api_key,
            "no_cache": "true",  # a cached hit would not prove a live search
        }

        try:
            resp = requests.get(ENDPOINT, params=params, timeout=self.timeout)
        except Exception as exc:
            raise SearchError(f"SerpApi request failed: {exc}") from exc

        if resp.status_code == 401:
            raise SearchError("SerpApi rejected the key (HTTP 401)")
        if resp.status_code == 429:
            raise SearchError(
                "SerpApi quota exhausted (HTTP 429). Switch SEARCH_PROVIDER to "
                "tineye, or top up the account."
            )
        if resp.status_code != 200:
            raise SearchError(f"SerpApi returned HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise SearchError(f"SerpApi response was not JSON: {resp.text[:300]}") from exc

        if isinstance(data, dict) and data.get("error"):
            raise SearchError(f"SerpApi error: {data['error']}")

        candidates = self._parse(data, max_results)
        return SearchResult(
            provider=self.name,
            endpoint=ENDPOINT,
            searched_at=utc_now(),
            candidates=candidates,
            raw_response=data,
            query_image_url=image_url,
            quota_note=str(
                (data.get("search_metadata") or {}).get("id", "")
                if isinstance(data, dict)
                else ""
            ),
        )

    @staticmethod
    def _parse(data: Any, max_results: int) -> list[Candidate]:
        out: list[Candidate] = []
        seen: set[str] = set()
        if not isinstance(data, dict):
            return out

        for key in _RESULT_KEYS:
            block = data.get(key)
            if not isinstance(block, list):
                continue
            for item in block:
                if not isinstance(item, dict):
                    continue
                page_url = str(item.get("link") or item.get("source_url") or "").strip()
                if not page_url or page_url in seen:
                    continue
                seen.add(page_url)
                out.append(
                    Candidate(
                        page_url=page_url,
                        image_url=str(item.get("image") or item.get("original") or ""),
                        title=str(item.get("title") or ""),
                        source=str(item.get("source") or key),
                        thumbnail=str(item.get("thumbnail") or ""),
                        position=int(item.get("position") or (len(out) + 1)),
                        raw=item,
                    )
                )
                if len(out) >= max_results:
                    return out
        return out
