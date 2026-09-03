"""
TinEye backend.

Kept as the second provider for two reasons. It accepts a direct **multipart
upload**, so it works when the image-publishing step fails or when you would
rather not put the query image on a public host at all. And it indexes by image
derivation rather than semantic similarity, so it finds crops, re-encodes and
recolours that Lens sometimes misses.

Its weakness is coverage of social platforms, which is why it is not the
default: TinEye is excellent at "where else does this exact image appear" and
weaker at surfacing the specific post.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..record import utc_now
from .base import Candidate, ReverseSearchProvider, SearchError, SearchResult

ENDPOINT = "https://api.tineye.com/rest/search/"


class TinEyeProvider(ReverseSearchProvider):
    name = "tineye"
    needs_public_url = False

    def __init__(self, api_key: str, *, timeout: int = 90) -> None:
        if not api_key:
            raise SearchError(
                "TINEYE_API_KEY is not set. Get one at https://services.tineye.com/ "
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

        path = Path(image_path)
        if not path.exists():
            raise SearchError(f"no such image: {path}")

        try:
            with path.open("rb") as fh:
                resp = requests.post(
                    ENDPOINT,
                    headers={"X-API-Key": self.api_key},
                    files={"image_upload": (path.name, fh, "application/octet-stream")},
                    data={"limit": str(max_results), "sort": "score", "order": "desc"},
                    timeout=self.timeout,
                )
        except Exception as exc:
            raise SearchError(f"TinEye request failed: {exc}") from exc

        if resp.status_code in (401, 403):
            raise SearchError(f"TinEye rejected the key (HTTP {resp.status_code})")
        if resp.status_code == 429:
            raise SearchError("TinEye quota exhausted (HTTP 429)")
        if resp.status_code != 200:
            raise SearchError(f"TinEye returned HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise SearchError(f"TinEye response was not JSON: {resp.text[:300]}") from exc

        # TinEye reports application-level failures inside a 200 response.
        status = str(data.get("status", "")).lower() if isinstance(data, dict) else ""
        if status and status not in ("ok", "success"):
            messages = data.get("messages") or data.get("error") or status
            raise SearchError(f"TinEye error: {messages}")

        return SearchResult(
            provider=self.name,
            endpoint=ENDPOINT,
            searched_at=utc_now(),
            candidates=self._parse(data, max_results),
            raw_response=data,
            query_image_url="",
        )

    @staticmethod
    def _parse(data: Any, max_results: int) -> list[Candidate]:
        out: list[Candidate] = []
        seen: set[str] = set()
        if not isinstance(data, dict):
            return out

        results = data.get("results")
        matches = []
        if isinstance(results, dict):
            matches = results.get("matches") or []
        elif isinstance(results, list):
            matches = results
        if not isinstance(matches, list):
            return out

        for position, match in enumerate(matches, start=1):
            if not isinstance(match, dict):
                continue
            match_image = str(match.get("image_url") or "")
            backlinks = match.get("backlinks")
            if not isinstance(backlinks, list) or not backlinks:
                continue
            for link in backlinks:
                if not isinstance(link, dict):
                    continue
                # TinEye's naming is counter-intuitive: `backlink` is the page
                # the image was found on, `url` is the image itself.
                page_url = str(link.get("backlink") or "").strip()
                direct = str(link.get("url") or "")
                if not page_url:
                    page_url, direct = direct, match_image
                if not page_url or page_url in seen:
                    continue
                seen.add(page_url)
                out.append(
                    Candidate(
                        page_url=page_url,
                        image_url=direct or match_image,
                        title=str(link.get("crawl_date") or ""),
                        source=str(match.get("domain") or ""),
                        thumbnail="",
                        position=position,
                        raw={"match": {k: v for k, v in match.items() if k != "backlinks"},
                             "backlink": link},
                    )
                )
                if len(out) >= max_results:
                    return out
        return out
