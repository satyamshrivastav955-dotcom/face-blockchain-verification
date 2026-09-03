"""
Search adapters: domain logic, ranking, and response parsing.

The parsers are tested against captured-shape responses rather than live calls.
That is not a compromise: the failure this guards against is a provider quietly
renaming a key, and a fixture pinning the expected shape is what makes that
visible instead of returning zero candidates on demo night.
"""

from __future__ import annotations

import json

import pytest

from src.config import SOCIAL_DOMAINS, Settings
from src.search import (
    PROVIDERS,
    Candidate,
    SearchError,
    build_provider,
    domain_of,
    is_social,
    rank_candidates,
)
from src.search.serpapi_lens import SerpApiLensProvider
from src.search.tineye import TinEyeProvider


class TestDomainOf:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.instagram.com/p/abc/", "instagram.com"),
            ("https://x.com/user/status/1", "x.com"),
            ("http://EXAMPLE.COM/Path", "example.com"),
            ("https://sub.domain.co.uk/x", "sub.domain.co.uk"),
            ("not a url", ""),
            ("", ""),
        ],
    )
    def test_cases(self, url, expected):
        assert domain_of(url) == expected


class TestIsSocial:
    @pytest.mark.parametrize(
        "url",
        [
            "https://instagram.com/p/abc/",
            "https://www.instagram.com/p/abc/",
            "https://x.com/u/status/1",
            "https://mobile.twitter.com/u/status/1",
            "https://old.reddit.com/r/pics/comments/x/",
        ],
    )
    def test_social_urls(self, url):
        assert is_social(url, SOCIAL_DOMAINS)

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/page",
            "https://news.bbc.co.uk/story",
            "https://notinstagram.com/p/abc",  # suffix must not match loosely
            "",
        ],
    )
    def test_non_social_urls(self, url):
        assert not is_social(url, SOCIAL_DOMAINS)


class TestRanking:
    def test_social_first_order_otherwise_preserved(self):
        candidates = [
            Candidate(page_url="https://a.example.com/1", position=1),
            Candidate(page_url="https://x.com/u/status/1", position=2),
            Candidate(page_url="https://b.example.com/2", position=3),
            Candidate(page_url="https://instagram.com/p/z/", position=4),
        ]
        ranked = rank_candidates(candidates, SOCIAL_DOMAINS)
        assert [c.position for c in ranked] == [2, 4, 1, 3]

    def test_nothing_is_discarded(self):
        candidates = [Candidate(page_url=f"https://e{i}.example.com/") for i in range(5)]
        assert len(rank_candidates(candidates, SOCIAL_DOMAINS)) == 5

    def test_empty(self):
        assert rank_candidates([], SOCIAL_DOMAINS) == []


class TestCandidate:
    def test_prefers_full_image_over_thumbnail(self):
        c = Candidate(
            page_url="https://x.com/a",
            image_url="https://cdn/full.jpg",
            thumbnail="https://cdn/thumb.jpg",
        )
        assert c.best_image_url() == "https://cdn/full.jpg"

    def test_falls_back_to_thumbnail(self):
        c = Candidate(page_url="https://x.com/a", thumbnail="https://cdn/thumb.jpg")
        assert c.best_image_url() == "https://cdn/thumb.jpg"

    def test_no_image_at_all(self):
        assert Candidate(page_url="https://x.com/a").best_image_url() == ""


class TestSerpApiParsing:
    RESPONSE = {
        "search_metadata": {"id": "abc123", "status": "Success"},
        "exact_matches": [
            {
                "position": 1,
                "title": "the genuine post",
                "link": "https://x.com/realuser/status/1234567890",
                "source": "X",
                "thumbnail": "https://serpapi/thumb1.jpg",
                "image": "https://pbs.twimg.com/media/full1.jpg",
            }
        ],
        "visual_matches": [
            {
                "position": 1,
                "title": "a stock photo site",
                "link": "https://stock.example.com/photo/99",
                "image": "https://stock.example.com/full.jpg",
            },
            {  # duplicate link, must be de-duplicated
                "position": 2,
                "link": "https://x.com/realuser/status/1234567890",
                "image": "https://pbs.twimg.com/media/full1.jpg",
            },
        ],
    }

    def test_reads_multiple_result_blocks(self):
        candidates = SerpApiLensProvider._parse(self.RESPONSE, 25)
        assert [c.page_url for c in candidates] == [
            "https://x.com/realuser/status/1234567890",
            "https://stock.example.com/photo/99",
        ]

    def test_exact_matches_come_first(self):
        """Priority order matters: exact matches are the strongest leads."""
        candidates = SerpApiLensProvider._parse(self.RESPONSE, 25)
        assert candidates[0].domain == "x.com"

    def test_extracts_image_and_title(self):
        first = SerpApiLensProvider._parse(self.RESPONSE, 25)[0]
        assert first.image_url == "https://pbs.twimg.com/media/full1.jpg"
        assert first.title == "the genuine post"
        assert first.raw  # the provider's own item is kept for the evidence bundle

    def test_respects_max_results(self):
        assert len(SerpApiLensProvider._parse(self.RESPONSE, 1)) == 1

    def test_tolerates_alternative_key_names(self):
        data = {"image_results": [{"source_url": "https://x.com/a/status/1", "original": "https://c/i.jpg"}]}
        candidates = SerpApiLensProvider._parse(data, 25)
        assert candidates[0].page_url == "https://x.com/a/status/1"
        assert candidates[0].image_url == "https://c/i.jpg"

    def test_tolerates_junk(self):
        assert SerpApiLensProvider._parse({}, 25) == []
        assert SerpApiLensProvider._parse([], 25) == []
        assert SerpApiLensProvider._parse({"visual_matches": "nope"}, 25) == []
        assert SerpApiLensProvider._parse({"visual_matches": [None, 5, {}]}, 25) == []

    def test_missing_key_is_explained(self):
        with pytest.raises(SearchError) as excinfo:
            SerpApiLensProvider("")
        assert "SERPAPI_KEY" in str(excinfo.value)

    def test_needs_a_public_url(self):
        assert SerpApiLensProvider("fake-key").needs_public_url is True
        assert SerpApiLensProvider("fake-key").is_offline_stub is False


class TestTinEyeParsing:
    RESPONSE = {
        "status": "ok",
        "results": {
            "matches": [
                {
                    "image_url": "https://tineye.example/match1.jpg",
                    "domain": "instagram.com",
                    "backlinks": [
                        {
                            # TinEye's naming is inverted: backlink = page, url = image
                            "backlink": "https://instagram.com/p/AbCdEf/",
                            "url": "https://scontent.example/full.jpg",
                            "crawl_date": "2026-01-05",
                        }
                    ],
                }
            ]
        },
    }

    def test_backlink_is_the_page_not_the_image(self):
        candidate = TinEyeProvider._parse(self.RESPONSE, 25)[0]
        assert candidate.page_url == "https://instagram.com/p/AbCdEf/"
        assert candidate.image_url == "https://scontent.example/full.jpg"

    def test_matches_without_backlinks_are_skipped(self):
        data = {"results": {"matches": [{"image_url": "https://x/i.jpg"}]}}
        assert TinEyeProvider._parse(data, 25) == []

    def test_tolerates_junk(self):
        assert TinEyeProvider._parse({}, 25) == []
        assert TinEyeProvider._parse({"results": None}, 25) == []
        assert TinEyeProvider._parse({"results": {"matches": [None]}}, 25) == []

    def test_no_public_url_required(self):
        provider = TinEyeProvider("fake-key")
        assert provider.needs_public_url is False
        assert provider.is_offline_stub is False


class TestRegistry:
    def test_every_advertised_provider_is_constructible(self, tmp_path):
        settings = Settings()
        settings.serpapi_key = "fake"
        settings.tineye_api_key = "fake"
        fixture = tmp_path / "f.json"
        fixture.write_text(json.dumps({"candidates": []}), encoding="utf-8")
        settings.fixture_path = str(fixture)
        for name in PROVIDERS:
            assert build_provider(name, settings).name

    def test_aliases_resolve(self):
        settings = Settings()
        settings.serpapi_key = "fake"
        for alias in ("serpapi", "lens", "google_lens", "SerpApi_Lens"):
            assert build_provider(alias, settings).name == "serpapi_google_lens"

    def test_unknown_provider_lists_the_options(self):
        with pytest.raises(SearchError) as excinfo:
            build_provider("chatgpt", Settings())
        assert "serpapi_lens" in str(excinfo.value)

    def test_describe_names_the_real_endpoint(self, tmp_path):
        """`register` and `search` print describe() under the label "endpoint".

        If it returned the provider's name instead, the recording would show a
        line that reads like evidence of an outbound call while actually saying
        nothing - so every provider has to name the address it really contacts.
        """
        settings = Settings()
        settings.serpapi_key = "fake"
        settings.tineye_api_key = "fake"
        fixture = tmp_path / "f.json"
        fixture.write_text(json.dumps({"candidates": []}), encoding="utf-8")
        settings.fixture_path = str(fixture)

        expected = {
            "serpapi_lens": "https://serpapi.com/search.json",
            "tineye": "https://api.tineye.com/rest/search/",
            "local_fixture": f"file://{fixture}",
        }
        for name in PROVIDERS:
            provider = build_provider(name, settings)
            assert provider.describe() == expected[name]
            assert provider.describe() != provider.name


class TestLocalFixtureProvider:
    def test_is_flagged_as_a_stub(self, tmp_path):
        fixture = tmp_path / "f.json"
        fixture.write_text(
            json.dumps({"candidates": [{"page_url": "https://x.com/a/status/1"}]}),
            encoding="utf-8",
        )
        provider = build_provider("local_fixture", _settings_with_fixture(fixture))
        assert provider.is_offline_stub is True

    def test_records_declare_the_stub_provider(self, tmp_path):
        """A record made offline must say so, permanently, inside the hash."""
        fixture = tmp_path / "f.json"
        fixture.write_text(
            json.dumps({"candidates": [{"page_url": "https://x.com/a/status/1"}]}),
            encoding="utf-8",
        )
        provider = build_provider("local_fixture", _settings_with_fixture(fixture))
        result = provider.search(tmp_path / "unused.png")
        assert result.provider == "local_fixture"
        assert "OFFLINE" in result.quota_note

    def test_relative_paths_resolve_against_the_fixture(self, tmp_path):
        (tmp_path / "img.png").write_bytes(b"not really a png")
        fixture = tmp_path / "f.json"
        fixture.write_text(
            json.dumps({"candidates": [{"page_url": "https://x.com/a", "image_url": "img.png"}]}),
            encoding="utf-8",
        )
        provider = build_provider("local_fixture", _settings_with_fixture(fixture))
        candidate = provider.search(tmp_path / "unused.png").candidates[0]
        assert candidate.image_url.endswith("img.png")
        assert "/" in candidate.image_url or "\\" in candidate.image_url

    def test_missing_fixture_path_is_explained(self):
        with pytest.raises(SearchError) as excinfo:
            build_provider("local_fixture", Settings())
        assert "FIXTURE_PATH" in str(excinfo.value)

    def test_missing_fixture_file_is_explained(self, tmp_path):
        provider = build_provider(
            "local_fixture", _settings_with_fixture(tmp_path / "absent.json")
        )
        with pytest.raises(SearchError):
            provider.search(tmp_path / "unused.png")


def _settings_with_fixture(path) -> Settings:
    settings = Settings()
    settings.fixture_path = str(path)
    return settings
