"""
Offline fixture backend - DEVELOPMENT AND TESTS ONLY.

This provider reads candidates from a local JSON file instead of querying a
search engine. It exists so the rest of the pipeline (confirmation, hashing,
anchoring, verification, tamper detection) can be developed and tested in an
environment with no network access, and so CI can run without API keys.

It must never be used for the graded run. Two safeguards make misuse
self-evident rather than relying on discipline:

* ``is_offline_stub = True``, which makes the CLI print a prominent warning and
  refuse to run unless ``--allow-offline-stub`` is passed explicitly;
* the provider name is written into the hashed payload, so any record produced
  this way permanently and visibly declares ``"provider": "local_fixture"``.

Fixture format::

    {
      "candidates": [
        {"page_url": "https://x.com/a/status/1",
         "image_url": "tests/data/candidate_a.png",
         "title": "post title",
         "source": "x.com"}
      ]
    }

``image_url`` may be a local path, which :mod:`src.confirm` loads from disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..record import utc_now
from .base import Candidate, ReverseSearchProvider, SearchError, SearchResult


class LocalFixtureProvider(ReverseSearchProvider):
    name = "local_fixture"
    needs_public_url = False
    is_offline_stub = True

    def __init__(self, fixture_path: str | Path) -> None:
        if not fixture_path:
            raise SearchError(
                "the local_fixture provider needs FIXTURE_PATH (or --fixture) "
                "pointing at a candidates JSON file"
            )
        self.fixture_path = Path(fixture_path)

    def search(
        self,
        image_path: Path,
        *,
        image_url: str = "",
        max_results: int = 25,
    ) -> SearchResult:
        if not self.fixture_path.exists():
            raise SearchError(f"no fixture file at {self.fixture_path}")

        data = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        items = data.get("candidates") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise SearchError(
                f"{self.fixture_path}: expected a 'candidates' list"
            )

        # Relative paths in a fixture resolve against the fixture's own
        # directory tree, so the file stays portable.
        base = self.fixture_path.parent

        candidates: list[Candidate] = []
        for position, item in enumerate(items[:max_results], start=1):
            if not isinstance(item, dict):
                continue
            image_ref = str(item.get("image_url") or "")
            if image_ref and not image_ref.startswith(("http://", "https://")):
                resolved = (base / image_ref).resolve()
                if not resolved.exists():
                    resolved = (Path.cwd() / image_ref).resolve()
                image_ref = str(resolved)
            candidates.append(
                Candidate(
                    page_url=str(item.get("page_url") or ""),
                    image_url=image_ref,
                    title=str(item.get("title") or ""),
                    source=str(item.get("source") or ""),
                    thumbnail="",
                    position=position,
                    raw=item,
                )
            )

        return SearchResult(
            provider=self.name,
            endpoint=f"file://{self.fixture_path}",
            searched_at=utc_now(),
            candidates=candidates,
            raw_response=data,
            query_image_url="",
            quota_note="OFFLINE STUB - not a real search",
        )
