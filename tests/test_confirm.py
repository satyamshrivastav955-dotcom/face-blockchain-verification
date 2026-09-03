"""
Candidate confirmation: the decision rule that makes the match defensible.

What is being protected here is the claim "the result was not predetermined".
The tests therefore check that a genuine derivative is accepted, an unrelated
image is rejected, rejections are *kept* rather than discarded, and the
selection prefers a social-media page - all without any network.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.config import SOCIAL_DOMAINS
from src.confirm import (
    Confirmation,
    ConfirmationStatus,
    confirm_candidates,
    score_table,
    select_best,
)
from src.faces import StubFaceEngine
from src.imaging import phash
from src.search import Candidate

from conftest import make_blob, make_stripes, rewrite, write_png


def run(candidates, tmp_path, *, cosine=0.363, distance=12, **kwargs):
    engine = StubFaceEngine()
    query = make_blob()
    return confirm_candidates(
        query_embedding=engine.analyze(query)[0].embedding,
        query_phash=phash(query),
        candidates=candidates,
        engine=engine,
        cosine_threshold=cosine,
        phash_max_distance=distance,
        social_domains=SOCIAL_DOMAINS,
        **kwargs,
    )


@pytest.fixture
def match_candidate(tmp_path):
    path = write_png(tmp_path / "match.png", rewrite(make_blob()))
    return Candidate(
        page_url="https://x.com/user/status/1", image_url=str(path), position=1
    )


@pytest.fixture
def other_candidate(tmp_path):
    path = write_png(tmp_path / "other.png", make_stripes())
    return Candidate(
        page_url="https://example.org/page", image_url=str(path), position=2
    )


class TestDecisionRule:
    def test_genuine_derivative_is_confirmed(self, match_candidate, tmp_path):
        result = run([match_candidate], tmp_path)[0]
        assert result.confirmed
        assert result.status in ConfirmationStatus.CONFIRMED
        assert result.candidate_image_sha256

    def test_unrelated_image_is_rejected(self, other_candidate, tmp_path):
        result = run([other_candidate], tmp_path)[0]
        assert not result.confirmed
        assert result.status.startswith("rejected")

    def test_face_match_fires_when_similarity_passes(self, match_candidate, tmp_path):
        # Make the pHash test impossible to pass, so only the face rule can fire.
        result = run([match_candidate], tmp_path, distance=-1)[0]
        assert result.status == ConfirmationStatus.FACE_MATCH

    def test_phash_rule_rescues_a_low_face_score(self, match_candidate, tmp_path):
        """Covers the case where the face is too small or blurred to embed."""
        result = run([match_candidate], tmp_path, cosine=2.0, distance=12)[0]
        assert result.status == ConfirmationStatus.IMAGE_DERIVATIVE
        assert result.confirmed

    def test_threshold_is_inclusive(self, match_candidate, tmp_path):
        loose = run([match_candidate], tmp_path, cosine=0.0, distance=-1)[0]
        assert loose.status == ConfirmationStatus.FACE_MATCH

    def test_raising_the_threshold_rejects_everything(self, match_candidate, tmp_path):
        strict = run([match_candidate], tmp_path, cosine=1.5, distance=-1)[0]
        assert not strict.confirmed

    def test_both_scores_always_recorded(self, match_candidate, other_candidate, tmp_path):
        for result in run([match_candidate, other_candidate], tmp_path):
            assert result.phash_distance is not None
            assert 0.0 <= abs(result.face_similarity) <= 1.0


class TestEvidenceRetention:
    def test_rejections_are_kept(self, match_candidate, other_candidate, tmp_path):
        """A table with only winners in it proves nothing."""
        results = run([other_candidate, match_candidate], tmp_path)
        assert len(results) == 2
        assert sum(1 for r in results if r.confirmed) == 1
        assert sum(1 for r in results if not r.confirmed) == 1

    def test_missing_image_url_is_recorded_not_dropped(self, tmp_path):
        results = run([Candidate(page_url="https://x.com/a/status/9")], tmp_path)
        assert results[0].status == ConfirmationStatus.NO_IMAGE_URL

    def test_unreachable_image_is_recorded_with_the_error(self, tmp_path):
        candidate = Candidate(
            page_url="https://x.com/a/status/9",
            image_url=str(tmp_path / "does_not_exist.png"),
        )
        result = run([candidate], tmp_path)[0]
        assert result.status == ConfirmationStatus.DOWNLOAD_FAILED
        assert result.error

    def test_max_candidates_caps_work(self, match_candidate, other_candidate, tmp_path):
        results = run([other_candidate, match_candidate], tmp_path, max_candidates=1)
        assert len(results) == 1

    def test_stop_early_halts_on_a_confirmed_social_hit(
        self, match_candidate, other_candidate, tmp_path
    ):
        results = run(
            [match_candidate, other_candidate], tmp_path, stop_early=True
        )
        assert len(results) == 1
        assert results[0].confirmed

    def test_stop_early_does_not_halt_on_a_non_social_hit(self, tmp_path):
        path = write_png(tmp_path / "m.png", rewrite(make_blob()))
        news = Candidate(page_url="https://news.example.com/story", image_url=str(path))
        social = Candidate(page_url="https://x.com/u/status/2", image_url=str(path))
        results = run([news, social], tmp_path, stop_early=True)
        assert len(results) == 2

    def test_progress_callback_is_invoked(self, match_candidate, tmp_path):
        lines = []
        run([match_candidate], tmp_path, progress=lines.append)
        assert lines and any("cos=" in line for line in lines)


class TestSerialization:
    def test_to_json_has_no_floats_or_bytes(self, match_candidate, tmp_path):
        from src.canonical import canonicalize

        data = run([match_candidate], tmp_path)[0].to_json()
        canonicalize(data)  # raises on a float
        assert isinstance(data["face_similarity"], str)
        assert "candidate_image_bytes" not in data
        assert "embedding" not in data

    def test_missing_phash_serializes_as_minus_one(self):
        data = Confirmation(
            candidate=Candidate(page_url="https://x.com/a"),
            status=ConfirmationStatus.NO_IMAGE_URL,
        ).to_json()
        assert data["phash_distance"] == -1

    def test_error_is_truncated(self):
        data = Confirmation(
            candidate=Candidate(page_url="https://x.com/a"),
            status=ConfirmationStatus.DOWNLOAD_FAILED,
            error="x" * 500,
        ).to_json()
        assert len(data["error"]) == 200


class TestSelectBest:
    def _c(self, url, *, confirmed=True, sim=0.8, dist=4, social=True):
        return Confirmation(
            candidate=Candidate(page_url=url),
            status=(
                ConfirmationStatus.FACE_MATCH if confirmed else ConfirmationStatus.LOW_SIMILARITY
            ),
            face_similarity=sim,
            phash_distance=dist,
            social=social,
        )

    def test_returns_none_when_nothing_confirmed(self):
        assert select_best([self._c("https://x.com/a", confirmed=False)]) is None

    def test_empty_input(self):
        assert select_best([]) is None

    def test_prefers_social_media(self):
        best = select_best(
            [
                self._c("https://news.example.com/a", sim=0.95, social=False),
                self._c("https://x.com/u/status/1", sim=0.70, social=True),
            ]
        )
        assert best.candidate.domain == "x.com"

    def test_falls_back_to_non_social_when_that_is_all_there_is(self):
        best = select_best([self._c("https://news.example.com/a", social=False)])
        assert best.candidate.domain == "news.example.com"

    def test_highest_similarity_wins_within_a_group(self):
        best = select_best(
            [
                self._c("https://x.com/a/status/1", sim=0.55),
                self._c("https://x.com/b/status/2", sim=0.91),
            ]
        )
        assert best.candidate.page_url.endswith("2")

    def test_phash_breaks_a_similarity_tie(self):
        best = select_best(
            [
                self._c("https://x.com/a/status/1", sim=0.80, dist=9),
                self._c("https://x.com/b/status/2", sim=0.80, dist=2),
            ]
        )
        assert best.candidate.page_url.endswith("2")

    def test_ignores_unconfirmed_even_with_a_higher_score(self):
        best = select_best(
            [
                self._c("https://x.com/a/status/1", sim=0.99, confirmed=False),
                self._c("https://x.com/b/status/2", sim=0.40, confirmed=True),
            ]
        )
        assert best.candidate.page_url.endswith("2")


class TestScoreTable:
    def test_lists_every_candidate(self, match_candidate, other_candidate, tmp_path):
        table = score_table(run([match_candidate, other_candidate], tmp_path))
        assert "x.com" in table and "example.org" in table
        assert "cosine" in table and "pHash" in table

    def test_truncates_politely(self):
        rows = [
            Confirmation(
                candidate=Candidate(page_url=f"https://x.com/{i}"),
                status=ConfirmationStatus.LOW_SIMILARITY,
                phash_distance=30,
            )
            for i in range(40)
        ]
        table = score_table(rows, limit=5)
        assert "and 35 more" in table
