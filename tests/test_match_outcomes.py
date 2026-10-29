"""
Match outcomes: face evidence and image-derivative evidence must never be conflated.

A perceptual-hash-only match is *image similarity*. It may be registered, but
only as an image-derivative claim - never described as a confirmed face match.
These tests pin every outcome, the boundaries, the deterministic selection and
the wording of each claim, using a scripted face engine so the similarity score
is exactly what the test says it is.
"""

from __future__ import annotations

import itertools
import json
import math

import numpy as np
import pytest

from src.config import SOCIAL_DOMAINS
from src.evidence.record import load_record
from src.pipeline import EXIT_ERROR, EXIT_NO_MATCH, EXIT_OK, run_register
from src.search import Candidate
from src.ui import Console
from src.verification.candidate_matcher import (
    Confirmation,
    ConfirmationStatus as S,
    claim_for,
    classify,
    confirm_candidates,
    select_best,
)
from src.vision.face_detector import Face
from src.vision.preprocess import DownloadError, UnsafeDownloadError, phash

from conftest import make_blob, make_stripes, rewrite, write_png

QUERY_VEC = np.zeros(128, dtype=np.float32)
QUERY_VEC[0] = 1.0
SAME_VEC = QUERY_VEC.copy()  # cosine 1.0
OTHER_VEC = np.zeros(128, dtype=np.float32)
OTHER_VEC[1] = 1.0  # cosine 0.0


def face(vec, size=100):
    return Face(
        bbox=(0, 0, size, size),
        det_score=0.9,
        landmarks=[(0, 0)] * 5,
        embedding=None if vec is None else np.asarray(vec, dtype=np.float32),
        aligned=np.zeros((112, 112, 3), dtype=np.uint8),
    )


class ScriptedEngine:
    """Returns the faces scripted for an image by its width (a stand-in model)."""

    name = "scripted-test-engine"

    def __init__(self, by_width):
        self.by_width = by_width

    def analyze(self, img):
        return list(self.by_width.get(img.shape[1], []))


def run(tmp_path, items, *, cosine=0.363, distance=12, engine=None, **kwargs):
    """items: list of (image_array, page_url, faces) -> confirmations.

    Each image gets a unique width so the scripted engine can tell them apart.
    """
    candidates, script = [], {}
    for i, (img, page, faces) in enumerate(items, start=1):
        img = img[:, : img.shape[1]]
        path = write_png(tmp_path / f"c{i}.png", img)
        candidates.append(Candidate(page_url=page, image_url=str(path), position=i))
        script[img.shape[1]] = faces
    query = make_blob()
    return confirm_candidates(
        query_embedding=QUERY_VEC,
        query_phash=phash(query),
        candidates=candidates,
        engine=engine or ScriptedEngine(script),
        cosine_threshold=cosine,
        phash_max_distance=distance,
        social_domains=SOCIAL_DOMAINS,
        allow_local_files=True,
        **kwargs,
    )


SIMILAR = rewrite(make_blob())  # near-identical image: small pHash distance
DIFFERENT = make_stripes(200)  # unrelated image: large pHash distance


class TestOutcomes:
    def test_face_match_only(self, tmp_path):
        (c,) = run(tmp_path, [(DIFFERENT, "https://x.com/a/1", [face(SAME_VEC)])])
        assert c.status == S.FACE_MATCH
        assert c.face_check_passed and not c.derivative_check_passed
        assert c.evidence_type == "face_match"

    def test_image_derivative_only(self, tmp_path):
        (c,) = run(tmp_path, [(SIMILAR, "https://x.com/a/1", [face(OTHER_VEC)])])
        assert c.status == S.IMAGE_DERIVATIVE
        assert c.derivative_check_passed and not c.face_check_passed
        assert c.evidence_type == "image_derivative"

    def test_both_pass_is_a_face_match_and_records_both(self, tmp_path):
        (c,) = run(tmp_path, [(SIMILAR, "https://x.com/a/1", [face(SAME_VEC)])])
        assert c.status == S.FACE_MATCH
        assert c.face_check_passed and c.derivative_check_passed

    def test_both_fail(self, tmp_path):
        (c,) = run(tmp_path, [(DIFFERENT, "https://x.com/a/1", [face(OTHER_VEC)])])
        assert c.status == S.LOW_SIMILARITY
        assert not c.confirmed and not c.failed
        assert c.candidate_image_bytes is None  # rejected bytes are not retained

    def test_no_face_and_far_image_is_rejected_no_face(self, tmp_path):
        (c,) = run(tmp_path, [(DIFFERENT, "https://x.com/a/1", [])])
        assert c.status == S.NO_FACE

    def test_no_face_but_near_image_is_still_a_derivative_never_a_face_match(self, tmp_path):
        (c,) = run(tmp_path, [(SIMILAR, "https://x.com/a/1", [])])
        assert c.status == S.IMAGE_DERIVATIVE
        assert not c.face_check_passed

    def test_unembeddable_face_cannot_pass_the_face_test(self, tmp_path):
        (c,) = run(tmp_path, [(DIFFERENT, "https://x.com/a/1", [face(None)])], cosine=-0.99)
        assert c.status == S.NO_FACE and c.faces_in_candidate == 1

    def test_multiple_faces_best_one_is_scored(self, tmp_path):
        faces = [face(OTHER_VEC, 300), face(SAME_VEC, 20), face(OTHER_VEC, 50)]
        (c,) = run(tmp_path, [(DIFFERENT, "https://x.com/a/1", faces)])
        assert c.status == S.FACE_MATCH
        assert c.faces_in_candidate == 3 and c.face_similarity == pytest.approx(1.0)

    def test_missing_image_url_is_skipped_not_negative(self, tmp_path):
        (c,) = confirm_candidates(
            query_embedding=QUERY_VEC,
            query_phash=0,
            candidates=[Candidate(page_url="https://x.com/a/1")],
            engine=ScriptedEngine({}),
            cosine_threshold=0.363,
            phash_max_distance=12,
            social_domains=SOCIAL_DOMAINS,
        )
        assert c.status == S.NO_IMAGE_URL and c.failed and not c.confirmed

    def test_download_failure_is_distinct_from_a_negative(self, monkeypatch):
        import src.verification.candidate_matcher as cm

        def boom(url, session=None):
            raise DownloadError("HTTP 503")

        monkeypatch.setattr(cm, "fetch_image", boom)
        (c,) = confirm_candidates(
            query_embedding=QUERY_VEC,
            query_phash=0,
            candidates=[Candidate(page_url="https://x.com/a", image_url="https://cdn.example/i.jpg")],
            engine=ScriptedEngine({}),
            cosine_threshold=0.363,
            phash_max_distance=12,
            social_domains=SOCIAL_DOMAINS,
        )
        assert c.status == S.DOWNLOAD_FAILED and c.failed
        assert "503" in c.error

    def test_blocked_url_is_reported_as_blocked(self, monkeypatch):
        import src.verification.candidate_matcher as cm

        def blocked(url, session=None):
            raise UnsafeDownloadError("refused URL: private address")

        monkeypatch.setattr(cm, "fetch_image", blocked)
        (c,) = confirm_candidates(
            query_embedding=QUERY_VEC,
            query_phash=0,
            candidates=[Candidate(page_url="https://x.com/a", image_url="http://169.254.169.254/x")],
            engine=ScriptedEngine({}),
            cosine_threshold=0.363,
            phash_max_distance=12,
            social_domains=SOCIAL_DOMAINS,
        )
        assert c.status == S.URL_BLOCKED

    def test_local_paths_are_refused_unless_the_offline_fixture_opted_in(self, tmp_path):
        path = write_png(tmp_path / "x.png", SIMILAR)
        (c,) = confirm_candidates(
            query_embedding=QUERY_VEC,
            query_phash=0,
            candidates=[Candidate(page_url="https://x.com/a", image_url=str(path))],
            engine=ScriptedEngine({}),
            cosine_threshold=0.363,
            phash_max_distance=12,
            social_domains=SOCIAL_DOMAINS,  # allow_local_files defaults to False
        )
        assert c.status == S.URL_BLOCKED

    def test_engine_crash_is_a_skip_not_an_abort(self, tmp_path):
        class Crashing:
            name = "crash"

            def analyze(self, img):
                raise RuntimeError("model exploded")

        results = run(tmp_path, [(SIMILAR, "https://x.com/a/1", [])], engine=Crashing())
        assert results[0].status == S.ANALYSIS_FAILED and results[0].failed


class TestBoundaries:
    @pytest.mark.parametrize(
        "similarity,expected",
        [
            (0.363, S.FACE_MATCH),
            (0.3631, S.FACE_MATCH),
            (0.3629, S.LOW_SIMILARITY),
            (1.0, S.FACE_MATCH),
            (-1.0, S.LOW_SIMILARITY),
        ],
    )
    def test_face_threshold_is_inclusive(self, similarity, expected):
        assert (
            classify(
                face_similarity=similarity,
                embeddable_faces=1,
                phash_distance=40,
                cosine_threshold=0.363,
                phash_max_distance=12,
            )
            == expected
        )

    @pytest.mark.parametrize(
        "distance,expected",
        [
            (0, S.IMAGE_DERIVATIVE),
            (12, S.IMAGE_DERIVATIVE),
            (13, S.LOW_SIMILARITY),
            (64, S.LOW_SIMILARITY),
            (-1, S.LOW_SIMILARITY),
            (None, S.LOW_SIMILARITY),
        ],
    )
    def test_phash_threshold_is_inclusive(self, distance, expected):
        assert (
            classify(
                face_similarity=0.0,
                embeddable_faces=1,
                phash_distance=distance,
                cosine_threshold=0.363,
                phash_max_distance=12,
            )
            == expected
        )

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_non_finite_similarity_never_passes(self, bad):
        assert (
            classify(
                face_similarity=bad, embeddable_faces=1, phash_distance=40, cosine_threshold=0.0, phash_max_distance=12
            )
            == S.LOW_SIMILARITY
        )

    def test_no_embeddable_face_never_passes_even_with_a_zero_threshold(self):
        assert (
            classify(
                face_similarity=0.0, embeddable_faces=0, phash_distance=40, cosine_threshold=0.0, phash_max_distance=12
            )
            == S.NO_FACE
        )

    def test_config_rejects_nonsense_thresholds(self):
        from src.config import ConfigError, Settings

        for field, value in [
            ("face_cosine_threshold", 1.5),
            ("face_cosine_threshold", float("nan")),
            ("phash_max_distance", 65),
            ("phash_max_distance", -1),
            ("max_candidates", 0),
        ]:
            s = Settings()
            setattr(s, field, value)
            with pytest.raises(ConfigError):
                s.validate()


def conf(page, status, *, sim=0.0, dist=30, social=False, position=1, image="i"):
    return Confirmation(
        candidate=Candidate(page_url=page, image_url=image, position=position),
        status=status,
        face_similarity=sim,
        phash_distance=dist,
        social=social,
    )


class TestSelection:
    def test_no_candidates_passing(self):
        assert (
            select_best(
                [
                    conf("https://a/1", S.LOW_SIMILARITY),
                    conf("https://a/2", S.NO_FACE),
                    conf("https://a/3", S.DOWNLOAD_FAILED),
                ]
            )
            is None
        )
        assert select_best([]) is None

    def test_face_evidence_outranks_a_social_derivative(self):
        derivative = conf("https://x.com/a/1", S.IMAGE_DERIVATIVE, dist=0, social=True)
        face_hit = conf("https://example.org/p", S.FACE_MATCH, sim=0.4, social=False)
        assert select_best([derivative, face_hit]) is face_hit

    def test_social_then_similarity_then_distance_then_position_then_url(self):
        a = conf("https://example.org/a", S.FACE_MATCH, sim=0.9)
        b = conf("https://x.com/b", S.FACE_MATCH, sim=0.5, social=True)
        c = conf("https://x.com/c", S.FACE_MATCH, sim=0.7, social=True)
        d = conf("https://x.com/d", S.FACE_MATCH, sim=0.7, social=True, dist=3)
        e = conf("https://x.com/e", S.FACE_MATCH, sim=0.7, social=True, dist=3, position=0)
        f = conf("https://x.com/a", S.FACE_MATCH, sim=0.7, social=True, dist=3, position=0)
        assert select_best([a, b]) is b
        assert select_best([b, c]) is c
        assert select_best([c, d]) is d
        assert select_best([d, e]) is e
        assert select_best([e, f]) is f

    def test_selection_is_independent_of_input_order(self):
        items = [
            conf("https://x.com/1", S.IMAGE_DERIVATIVE, dist=2, social=True),
            conf("https://x.com/2", S.FACE_MATCH, sim=0.6, social=True, position=3),
            conf("https://x.com/3", S.FACE_MATCH, sim=0.6, social=True, position=2),
            conf("https://example.org/4", S.FACE_MATCH, sim=0.99),
        ]
        winners = {select_best(list(p)).candidate.page_url for p in itertools.permutations(items)}
        assert winners == {"https://x.com/3"}

    def test_require_face_match_excludes_derivatives(self):
        derivative = conf("https://x.com/a/1", S.IMAGE_DERIVATIVE, dist=0, social=True)
        assert select_best([derivative], allowed=(S.FACE_MATCH,)) is None
        assert select_best([derivative]) is derivative


class TestClaimWording:
    def test_face_match_claim(self):
        text = claim_for(S.FACE_MATCH)
        assert "face" in text and "not a statement of any person's identity" in text
        assert "perceptual" not in text

    def test_derivative_claim_does_not_assert_a_face_match(self):
        text = claim_for(S.IMAGE_DERIVATIVE)
        assert "perceptually similar" in text
        assert "did NOT independently confirm" in text
        assert "same face" not in text.replace("not that the same face", "")

    def test_no_claim_for_rejections_or_failures(self):
        for status in S.REJECTED + S.SKIPPED:
            with pytest.raises(ValueError):
                claim_for(status)


# -- end to end through the real pipeline with a scripted engine ----------------


class QueryVsCandidateEngine:
    """The 256px dark-cornered blob is the query; everything else is a 'candidate'."""

    name = "scripted-test-engine"
    embedding_dim = 128

    def __init__(self, candidate_vec):
        self.candidate_vec = candidate_vec

    def model_versions(self):
        return {"detector": "scripted", "recognizer": "scripted"}

    def analyze(self, img):
        is_query = img.shape[1] == 256 and int(img[0, 0, 0]) < 100
        vec = QUERY_VEC if is_query else self.candidate_vec
        return [face(vec)]


@pytest.fixture
def scripted(monkeypatch):
    import src.pipeline as pipeline

    def install(candidate_vec):
        monkeypatch.setattr(pipeline, "build_engine", lambda *a, **k: QueryVsCandidateEngine(candidate_vec))

    return install


def register(settings, scene, **kwargs):
    settings.fixture_path = str(scene["fixture"])
    return run_register(
        settings,
        scene["query"],
        provider_name="local_fixture",
        engine_name="stub",
        dry_run=True,
        allow_offline_stub=True,
        console=Console(force_ascii=True),
        **kwargs,
    )


class TestRegistrationOfEachOutcome:
    def test_derivative_only_is_registered_as_an_image_claim(self, settings, scene, scripted, capsys):
        scripted(OTHER_VEC)  # face test fails; the rewritten copy still matches by pHash
        assert register(settings, scene) == EXIT_OK
        out = capsys.readouterr().out
        assert "IMAGE-DERIVATIVE match" in out and "NOT confirm a match" in out
        assert "FACE MATCH on" not in out

        record = load_record(settings.output_dir / "verification.json")
        payload, match = record["payload"], record["payload"]["match"]
        assert payload["evidence_type"] == "image_derivative"
        assert match["evidence_type"] == "image_derivative"
        assert match["decision_rule"] == "confirmed_image_derivative"
        assert match["face_check_passed"] is False
        assert match["image_derivative_check_passed"] is True
        assert "did NOT independently confirm" in match["claim"]
        assert any("image similarity" in text for text in match["limitations"])

    def test_face_match_is_registered_as_a_face_claim(self, settings, scene, scripted):
        scripted(SAME_VEC)
        assert register(settings, scene) == EXIT_OK
        match = load_record(settings.output_dir / "verification.json")["payload"]["match"]
        assert match["evidence_type"] == "face_match"
        assert match["face_check_passed"] is True
        assert "similarity measurement" in match["claim"]

    def test_require_face_match_refuses_a_derivative_only_result(self, settings, scene, scripted, capsys):
        scripted(OTHER_VEC)
        code = register(settings, scene, require_face_match=True)
        assert code == EXIT_NO_MATCH
        assert "--require-face-match" in capsys.readouterr().out
        assert not (settings.output_dir / "verification.json").exists()

    def test_no_match_refuses_to_register(self, settings, tmp_path, query_image, scripted):
        scripted(OTHER_VEC)
        other = write_png(tmp_path / "far.png", make_stripes(200))
        fixture = tmp_path / "fx.json"
        fixture.write_text(
            json.dumps({"candidates": [{"page_url": "https://example.org/p", "image_url": str(other)}]}),
            encoding="utf-8",
        )
        assert register(settings, {"query": query_image, "fixture": fixture}) == EXIT_NO_MATCH
        assert not (settings.output_dir / "verification.json").exists()
        assert not (settings.root / "localchain.json").exists()  # nothing was anchored

    def test_all_candidates_failing_is_an_error_not_a_negative(self, settings, tmp_path, query_image, scripted, capsys):
        scripted(SAME_VEC)
        fixture = tmp_path / "fx.json"
        fixture.write_text(
            json.dumps(
                {"candidates": [{"page_url": "https://example.org/p", "image_url": str(tmp_path / "gone.png")}]}
            ),
            encoding="utf-8",
        )
        code = register(settings, {"query": query_image, "fixture": fixture})
        assert code == EXIT_ERROR
        assert "NOT a negative result" in capsys.readouterr().out

    def test_stub_engine_records_are_labelled_test_only(self, settings, scene):
        assert register(settings, scene) == EXIT_OK  # real (non-scripted) stub engine
        payload = load_record(settings.output_dir / "verification.json")["payload"]
        assert payload["test_mode"] == {"stub_engine": True, "offline_fixture_provider": True}
        assert payload["match"]["claim"].startswith("TEST ONLY")
        assert payload["face"]["engine"] == "stub-test-only"

    def test_comparison_image_and_candidate_table_agree_with_the_record(self, settings, scene, scripted):
        scripted(OTHER_VEC)
        assert register(settings, scene) == EXIT_OK
        run_dir = sorted(p for p in settings.evidence_dir.iterdir() if p.is_dir())[-1]
        rows = json.loads((run_dir / "candidates.json").read_text(encoding="utf-8"))
        match = load_record(settings.output_dir / "verification.json")["payload"]["match"]
        chosen = [r for r in rows if r["page_url"] == match["matched_url"]][0]
        assert chosen["status"] == match["decision_rule"] == "confirmed_image_derivative"
        assert chosen["evidence_type"] == "image_derivative"
        assert (run_dir / "comparison.png").exists()

    def test_minimal_evidence_saves_no_crops_or_candidate_bytes(self, settings, scene):
        assert register(settings, scene, minimal_evidence=True) == EXIT_OK
        run_dir = sorted(p for p in settings.evidence_dir.iterdir() if p.is_dir())[-1]
        names = {p.name for p in run_dir.iterdir()}
        assert not names & {"query_face.png", "matched_face.png", "matched_image.original", "comparison.png"}
        assert "manifest.json" in names
