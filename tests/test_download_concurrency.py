"""
Candidate downloads run in a bounded pool ahead of analysis, without changing results.

Network latency is simulated with sleeps inside a patched ``fetch_image``; the assertions
are about wall time, ordering, determinism, the concurrency bound and failure isolation.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

import src.verification.candidate_matcher as cm
from src.config import SOCIAL_DOMAINS
from src.search import Candidate
from src.verification.candidate_matcher import ConfirmationStatus as S
from src.vision.face_detector import Face
from src.vision.preprocess import DownloadError

from conftest import make_blob
import cv2

Q = np.zeros(128, np.float32)
Q[0] = 1.0


class Engine:
    name = "scripted"

    def analyze(self, img):
        v = np.zeros(128, np.float32)
        v[1] = 1.0
        return [Face(bbox=(0, 0, 9, 9), det_score=0.9, landmarks=[(0, 0)] * 5, embedding=v)]


def run(candidates, **kw):
    return cm.confirm_candidates(
        query_embedding=Q,
        query_phash=0,
        candidates=candidates,
        engine=Engine(),
        cosine_threshold=0.363,
        phash_max_distance=-1,
        social_domains=SOCIAL_DOMAINS,
        **kw,
    )


def cands(n):
    return [
        Candidate(page_url=f"https://example.org/{i}", image_url=f"https://cdn.example.com/{i}.png", position=i)
        for i in range(1, n + 1)
    ]


@pytest.fixture
def slow_fetch(monkeypatch):
    state = {"now": 0, "peak": 0, "calls": [], "lock": threading.Lock()}
    ok, buf = cv2.imencode(".png", make_blob(64))
    raw = buf.tobytes()

    def fetch(url, session=None):
        with state["lock"]:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            state["calls"].append(url)
        time.sleep(0.15)
        with state["lock"]:
            state["now"] -= 1
        if url.endswith("/3.png"):
            raise DownloadError("HTTP 503")
        return raw, make_blob(64)

    monkeypatch.setattr(cm, "fetch_image", fetch)
    return state


def test_parallel_downloads_are_much_faster_than_sequential(slow_fetch):
    t = time.perf_counter()
    results = run(cands(8), download_workers=4)
    parallel = time.perf_counter() - t
    assert parallel < 8 * 0.15 * 0.6, f"{parallel:.2f}s is not meaningfully parallel"
    assert len(results) == 8


def test_one_worker_is_the_sequential_baseline(slow_fetch):
    t = time.perf_counter()
    run(cands(4), download_workers=1)
    assert time.perf_counter() - t >= 4 * 0.15 * 0.9
    assert slow_fetch["peak"] == 1


def test_results_stay_in_candidate_order_and_are_deterministic(slow_fetch):
    first = [(r.candidate.position, r.status) for r in run(cands(10), download_workers=5)]
    second = [(r.candidate.position, r.status) for r in run(cands(10), download_workers=2)]
    assert first == second
    assert [p for p, _ in first] == list(range(1, 11))


def test_concurrency_is_bounded(slow_fetch):
    run(cands(20), download_workers=3)
    assert slow_fetch["peak"] <= 3


def test_a_failing_download_does_not_affect_its_neighbours(slow_fetch):
    results = run(cands(6), download_workers=3)
    by_pos = {r.candidate.position: r.status for r in results}
    assert by_pos[3] == S.DOWNLOAD_FAILED
    assert all(by_pos[i] == S.LOW_SIMILARITY for i in (1, 2, 4, 5, 6))


def test_the_window_limits_how_far_ahead_downloads_start(slow_fetch):
    """With stop_early the run stops after the first confirmed social hit; far-away candidates are never fetched."""
    candidates = cands(40)
    candidates[0] = Candidate(page_url="https://x.com/a/1", image_url="https://cdn.example.com/1.png", position=1)

    class Hit(Engine):
        def analyze(self, img):
            v = Q.copy()
            return [Face(bbox=(0, 0, 9, 9), det_score=0.9, landmarks=[(0, 0)] * 5, embedding=v)]

    results = cm.confirm_candidates(
        query_embedding=Q,
        query_phash=0,
        candidates=candidates,
        engine=Hit(),
        cosine_threshold=0.363,
        phash_max_distance=-1,
        social_domains=SOCIAL_DOMAINS,
        stop_early=True,
        download_workers=2,
    )
    assert len(results) == 1 and results[0].status == S.FACE_MATCH
    time.sleep(0.4)
    assert len(slow_fetch["calls"]) <= 2 * 2 + 2  # window of workers*2, plus in-flight slack: not all 40
