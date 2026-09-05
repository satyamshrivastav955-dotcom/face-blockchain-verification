"""
Independent local confirmation of search candidates.

THE POINT OF THIS MODULE
========================
A reverse-image search returns pages it *believes* contain the query image. If
the pipeline simply took the first result, the evidence would amount to "a
search engine said so", and there would be no way for a reader of the record to
distinguish a genuine match from a hardcoded URL.

So every candidate is re-checked locally, from scratch:

1. download the candidate image from the page's own image URL;
2. run the same detector and embedder used on the query image;
3. score face similarity (cosine) against the query embedding;
4. score perceptual-hash distance between the two images.

Only then is a match declared. The scores of *rejected* candidates are retained
too, which is what turns "trust me" into an auditable table: a hardcoded result
cannot produce a plausible distribution of near-misses.

DECISION RULE
=============
A candidate is confirmed if **either** test passes, because they fail in
different situations and each covers the other's blind spot:

* ``face_match`` - cosine similarity >= threshold (default 0.363, OpenCV's
  documented SFace cut-off for same-identity). Survives cropping, rescaling,
  recolouring and re-encoding, which social platforms all do routinely, so
  perceptual hashing alone would miss real matches.
* ``image_derivative`` - perceptual-hash Hamming distance <= threshold. Catches
  the case where the post contains the same image but the face is too small,
  blurred or angled for the detector, where face similarity alone would miss it.

Both scores are always recorded regardless of which rule fired, and the rule
that fired is named in the record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..evidence.hashing import fmt_score, sha256_bytes
from ..vision.face_detector import Face, best_similarity
from ..vision.preprocess import DownloadError, fetch_image, hamming, phash
from ..search import Candidate, is_social

__all__ = [
    "Confirmation",
    "ConfirmationStatus",
    "confirm_candidates",
    "select_best",
    "score_table",
]


class ConfirmationStatus:
    """Why a candidate was accepted or not. Recorded verbatim as evidence."""

    FACE_MATCH = "confirmed_face_match"
    IMAGE_DERIVATIVE = "confirmed_image_derivative"
    LOW_SIMILARITY = "rejected_low_similarity"
    NO_FACE = "rejected_no_face_in_candidate"
    NO_IMAGE_URL = "skipped_no_image_url"
    DOWNLOAD_FAILED = "skipped_download_failed"

    CONFIRMED = (FACE_MATCH, IMAGE_DERIVATIVE)


@dataclass
class Confirmation:
    """Outcome of independently checking one candidate."""

    candidate: Candidate
    status: str
    face_similarity: float = 0.0
    phash_distance: int | None = None
    faces_in_candidate: int = 0
    candidate_image_sha256: str = ""
    candidate_image_bytes: bytes | None = field(default=None, repr=False)
    candidate_face: Face | None = field(default=None, repr=False)
    social: bool = False
    error: str = ""

    @property
    def confirmed(self) -> bool:
        return self.status in ConfirmationStatus.CONFIRMED

    def to_json(self) -> dict[str, Any]:
        """Hashable summary: no floats, no raw bytes, no embeddings."""
        return {
            "page_url": self.candidate.page_url,
            "image_url": self.candidate.best_image_url(),
            "domain": self.candidate.domain,
            "provider_position": int(self.candidate.position),
            "is_social": bool(self.social),
            "status": self.status,
            "face_similarity": fmt_score(self.face_similarity),
            "phash_distance": (
                int(self.phash_distance) if self.phash_distance is not None else -1
            ),
            "faces_in_candidate": int(self.faces_in_candidate),
            "candidate_image_sha256": self.candidate_image_sha256,
            **({"error": self.error[:200]} if self.error else {}),
        }


def _load_candidate_image(url: str) -> tuple[bytes, np.ndarray]:
    """Fetch a candidate image from the web, or from disk for offline fixtures."""
    if url.startswith(("http://", "https://")):
        return fetch_image(url)

    # Only reachable through the local_fixture provider, which is test-only.
    path = Path(url)
    if not path.exists():
        raise DownloadError(f"no local candidate image at {path}")
    import cv2

    raw = path.read_bytes()
    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise DownloadError(f"could not decode local candidate image {path}")
    return raw, img


def confirm_candidates(
    *,
    query_embedding: np.ndarray,
    query_phash: int,
    candidates: list[Candidate],
    engine: Any,
    cosine_threshold: float,
    phash_max_distance: int,
    social_domains: tuple[str, ...],
    max_candidates: int = 25,
    stop_early: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[Confirmation]:
    """Check each candidate independently and return every result, in order.

    Rejections are returned alongside confirmations on purpose - the full score
    table is the evidence that no answer was predetermined.
    """
    say = progress or (lambda _msg: None)
    results: list[Confirmation] = []

    for index, candidate in enumerate(candidates[:max_candidates], start=1):
        social = is_social(candidate.page_url, social_domains)
        image_url = candidate.best_image_url()
        label = f"[{index}/{min(len(candidates), max_candidates)}] {candidate.domain or '?'}"

        if not image_url:
            say(f"  {label}: no image URL, skipping")
            results.append(
                Confirmation(
                    candidate=candidate,
                    status=ConfirmationStatus.NO_IMAGE_URL,
                    social=social,
                )
            )
            continue

        try:
            raw, image = _load_candidate_image(image_url)
        except Exception as exc:
            say(f"  {label}: download failed ({exc})")
            results.append(
                Confirmation(
                    candidate=candidate,
                    status=ConfirmationStatus.DOWNLOAD_FAILED,
                    social=social,
                    error=str(exc),
                )
            )
            continue

        distance = hamming(query_phash, phash(image))
        faces = engine.analyze(image)
        similarity, matched_face = best_similarity(query_embedding, faces)

        if similarity >= cosine_threshold:
            status = ConfirmationStatus.FACE_MATCH
        elif distance <= phash_max_distance:
            status = ConfirmationStatus.IMAGE_DERIVATIVE
        elif not faces:
            status = ConfirmationStatus.NO_FACE
        else:
            status = ConfirmationStatus.LOW_SIMILARITY

        confirmation = Confirmation(
            candidate=candidate,
            status=status,
            face_similarity=similarity,
            phash_distance=distance,
            faces_in_candidate=len(faces),
            candidate_image_sha256=sha256_bytes(raw),
            candidate_image_bytes=raw,
            candidate_face=matched_face,
            social=social,
        )
        results.append(confirmation)

        verdict = "CONFIRMED" if confirmation.confirmed else "rejected "
        say(
            f"  {label}: {verdict}  cos={fmt_score(similarity)}  "
            f"pHash={distance:2d}/64  faces={len(faces)}"
            f"{'  [social]' if social else ''}"
        )

        if stop_early and confirmation.confirmed and social:
            say("  stopping early on first confirmed social match")
            break

    return results


def select_best(confirmations: list[Confirmation]) -> Confirmation | None:
    """Pick the match to anchor, or None if nothing was confirmed.

    Ordering: confirmed only, social-media pages ahead of other sites (the task
    asks for a social post), then highest face similarity, then lowest
    perceptual-hash distance as a tie-break.
    """
    confirmed = [c for c in confirmations if c.confirmed]
    if not confirmed:
        return None
    return sorted(
        confirmed,
        key=lambda c: (
            not c.social,
            -c.face_similarity,
            c.phash_distance if c.phash_distance is not None else 65,
        ),
    )[0]


def score_table(confirmations: list[Confirmation], limit: int = 30) -> str:
    """Render the scores as a fixed-width table for the terminal.

    Printed during ``register`` so the reasoning is visible on the recording
    instead of buried in a JSON file.
    """
    header = (
        f"  {'#':>2}  {'cosine':>7}  {'pHash':>6}  {'faces':>5}  "
        f"{'soc':>3}  {'status':<32}  domain"
    )
    lines = [header, "  " + "-" * (len(header) - 2)]
    for i, c in enumerate(confirmations[:limit], start=1):
        distance = "-" if c.phash_distance is None else f"{c.phash_distance}/64"
        lines.append(
            f"  {i:>2}  {fmt_score(c.face_similarity):>7}  {distance:>6}  "
            f"{c.faces_in_candidate:>5}  {'yes' if c.social else ' no':>3}  "
            f"{c.status:<32}  {c.candidate.domain[:34]}"
        )
    if len(confirmations) > limit:
        lines.append(f"  ... and {len(confirmations) - limit} more")
    return "\n".join(lines)
