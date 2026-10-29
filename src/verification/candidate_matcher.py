"""
Independent local confirmation of search candidates.

THE POINT OF THIS MODULE
========================
A reverse-image search returns pages it *believes* contain the query image. If
the pipeline simply took the first result, the evidence would amount to "a
search engine said so". So every candidate is re-checked locally, from scratch:

1. download the candidate image from the page's own image URL (through the
   SSRF-guarded downloader);
2. run the same detector and embedder used on the query image;
3. score face similarity (cosine) against the query embedding;
4. score perceptual-hash distance between the two images.

The scores of *rejected* candidates are retained too: the full score table is
what lets a reader see that no answer was predetermined.

TWO KINDS OF EVIDENCE - DELIBERATELY NOT CONFLATED
==================================================
The two measurements answer different questions, so an accepted candidate is
labelled by *which* one supported it:

``confirmed_face_match``
    cosine similarity >= threshold for at least one face in the candidate
    image. Survives crops, rescaling and recolouring. Claim: "a face in the
    candidate image is similar to the query face under this model and
    threshold". It is a similarity measurement - never an identity statement.

``confirmed_image_derivative``
    perceptual-hash Hamming distance <= threshold *and the face test did not
    pass*. Catches the same picture re-encoded or resized when the face is too
    small, blurred or angled to detect. Claim: "the candidate image is
    perceptually similar to the query image". It says **nothing** about faces
    or people: a pHash-only match is image similarity, not biometric
    confirmation.

If both tests pass the candidate is a face match (the stronger kind) and the
record also notes that the derivative test passed. Both scores are always
recorded; the rule that fired is named in the record.

SELECTION POLICY (deterministic)
================================
Eligible outcomes default to both confirmed kinds; ``--require-face-match``
restricts registration to face matches. Among eligible candidates the order is:

1. face match before image derivative (stronger evidence first);
2. social-media domains before others;
3. higher face similarity;
4. lower pHash distance;
5. earlier provider position, then page URL and image URL (pure tie-breaks, so
   the choice never depends on input order).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from ..evidence.hashing import fmt_score, sha256_bytes
from ..search import Candidate, is_social
from ..vision.face_detector import Face, best_similarity
from ..vision.preprocess import (
    DownloadError,
    ImageError,
    UnsafeDownloadError,
    decode_image_safely,
    fetch_image,
    hamming,
    phash,
)

__all__ = [
    "Confirmation",
    "ConfirmationStatus",
    "EVIDENCE_TYPE",
    "classify",
    "claim_for",
    "limitations_for",
    "confirm_candidates",
    "select_best",
    "score_table",
]


class ConfirmationStatus:
    """Why a candidate was accepted or not. Recorded verbatim as evidence.

    ``confirmed_*`` and ``rejected_*`` are measurement outcomes. ``skipped_*``
    mean the measurement could not be made (technical failure) - they are not
    negative matches.
    """

    FACE_MATCH = "confirmed_face_match"
    IMAGE_DERIVATIVE = "confirmed_image_derivative"
    LOW_SIMILARITY = "rejected_low_similarity"
    NO_FACE = "rejected_no_face_in_candidate"
    NO_IMAGE_URL = "skipped_no_image_url"
    DOWNLOAD_FAILED = "skipped_download_failed"
    URL_BLOCKED = "skipped_url_blocked"
    ANALYSIS_FAILED = "skipped_analysis_failed"

    CONFIRMED = (FACE_MATCH, IMAGE_DERIVATIVE)
    REJECTED = (LOW_SIMILARITY, NO_FACE)
    SKIPPED = (NO_IMAGE_URL, DOWNLOAD_FAILED, URL_BLOCKED, ANALYSIS_FAILED)


EVIDENCE_TYPE = {
    ConfirmationStatus.FACE_MATCH: "face_match",
    ConfirmationStatus.IMAGE_DERIVATIVE: "image_derivative",
}


def _finite(value: float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def classify(
    *,
    face_similarity: float,
    embeddable_faces: int,
    phash_distance: int | None,
    cosine_threshold: float,
    phash_max_distance: int,
) -> str:
    """Pure decision rule: measurements in, status out.

    Boundaries are inclusive (``>=`` / ``<=``). A non-finite similarity, or a
    candidate with no embeddable face, can never pass the face test, however
    the threshold is configured.
    """
    face_ok = embeddable_faces > 0 and _finite(face_similarity) and face_similarity >= cosine_threshold
    derivative_ok = phash_distance is not None and 0 <= phash_distance <= phash_max_distance
    if face_ok:
        return ConfirmationStatus.FACE_MATCH
    if derivative_ok:
        return ConfirmationStatus.IMAGE_DERIVATIVE
    if embeddable_faces == 0:
        return ConfirmationStatus.NO_FACE
    return ConfirmationStatus.LOW_SIMILARITY


def claim_for(status: str) -> str:
    """The sentence a record may assert for an accepted outcome.

    Wording depends on the evidence type and never promotes image similarity to
    a face match.
    """
    if status == ConfirmationStatus.FACE_MATCH:
        return (
            "a face in the image at matched_image_url, published on matched_url, "
            "scored at or above the recorded face-similarity threshold against the "
            "primary face in source_image under the recorded models; this is a "
            "similarity measurement supporting image provenance, not a statement "
            "of any person's identity"
        )
    if status == ConfirmationStatus.IMAGE_DERIVATIVE:
        return (
            "the image at matched_image_url, published on matched_url, is "
            "perceptually similar to source_image (perceptual-hash distance within "
            "the recorded threshold), consistent with a resized, re-encoded or "
            "cropped copy; face matching did NOT independently confirm a match, so "
            "this asserts image similarity only, not that the same face or person "
            "appears"
        )
    raise ValueError(f"no claim is defined for status {status!r}")


def limitations_for(status: str) -> list[str]:
    common = [
        "a local record proves what the pipeline measured, not that the claim is true",
        "thresholds are model- and data-dependent and are not calibrated for any population",
    ]
    if status == ConfirmationStatus.IMAGE_DERIVATIVE:
        return [
            "perceptual hashing measures image similarity, not facial similarity",
            "the face test did not pass or was not possible for this candidate",
            *common,
        ]
    return [
        "face similarity is a model score, not proof of identity",
        "faces may be confused across look-alikes, ages, poses and image quality",
        *common,
    ]


@dataclass
class Confirmation:
    """Outcome of independently checking one candidate."""

    candidate: Candidate
    status: str
    face_similarity: float = 0.0
    phash_distance: int | None = None
    faces_in_candidate: int = 0
    embeddable_faces: int = 0
    candidate_image_sha256: str = ""
    candidate_image_bytes: bytes | None = field(default=None, repr=False)
    candidate_face: Face | None = field(default=None, repr=False)
    social: bool = False
    error: str = ""
    face_check_passed: bool = False
    derivative_check_passed: bool = False

    @property
    def confirmed(self) -> bool:
        return self.status in ConfirmationStatus.CONFIRMED

    @property
    def evidence_type(self) -> str:
        return EVIDENCE_TYPE.get(self.status, "")

    @property
    def failed(self) -> bool:
        """True when the measurement could not be made (not a negative result)."""
        return self.status in ConfirmationStatus.SKIPPED

    def to_json(self) -> dict[str, Any]:
        """Hashable summary: no floats, no raw bytes, no embeddings."""
        return {
            "page_url": self.candidate.page_url,
            "image_url": self.candidate.best_image_url(),
            "domain": self.candidate.domain,
            "provider_position": int(self.candidate.position),
            "is_social": bool(self.social),
            "status": self.status,
            "evidence_type": self.evidence_type,
            "face_similarity": fmt_score(self.face_similarity),
            "phash_distance": (int(self.phash_distance) if self.phash_distance is not None else -1),
            "faces_in_candidate": int(self.faces_in_candidate),
            "face_check_passed": bool(self.face_check_passed),
            "derivative_check_passed": bool(self.derivative_check_passed),
            "candidate_image_sha256": self.candidate_image_sha256,
            **({"error": self.error[:200]} if self.error else {}),
        }


def _load_candidate_image(url: str, *, allow_local_files: bool) -> tuple[bytes, np.ndarray]:
    """Fetch a candidate image from the web, or from disk for offline fixtures.

    Local paths are honoured ONLY when the offline fixture provider produced the
    candidates; for any real provider a non-HTTP image URL is refused, so a
    hostile search response cannot make the tool read local files.
    """
    if url.lower().startswith(("http://", "https://")):
        return fetch_image(url)
    if not allow_local_files:
        raise UnsafeDownloadError("refused URL: only http(s) image URLs are fetched")

    path = Path(url)
    if not path.is_file():
        raise DownloadError("no local candidate image at the given path")
    try:
        raw = path.read_bytes()
        return raw, decode_image_safely(raw, label="local candidate image")
    except (OSError, ImageError) as exc:
        raise DownloadError(f"could not read local candidate image: {exc}") from exc


def _skipped(candidate: Candidate, social: bool, status: str, error: str = "") -> Confirmation:
    return Confirmation(candidate=candidate, status=status, social=social, error=error)


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
    allow_local_files: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[Confirmation]:
    """Check each candidate independently and return every result, in order.

    Rejections and technical failures are returned alongside confirmations on
    purpose. To bound memory, raw candidate bytes and face crops are kept only
    for confirmed candidates.
    """
    say = progress or (lambda _msg: None)
    results: list[Confirmation] = []
    total = min(len(candidates), max_candidates)

    for index, candidate in enumerate(candidates[:max_candidates], start=1):
        social = is_social(candidate.page_url, social_domains)
        image_url = candidate.best_image_url()
        label = f"[{index}/{total}] {candidate.domain or '?'}"

        if not image_url:
            say(f"  {label}: no image URL, skipping (not a negative result)")
            results.append(_skipped(candidate, social, ConfirmationStatus.NO_IMAGE_URL))
            continue

        try:
            raw, image = _load_candidate_image(image_url, allow_local_files=allow_local_files)
        except UnsafeDownloadError as exc:
            say(f"  {label}: URL refused by the safety guard ({exc})")
            results.append(_skipped(candidate, social, ConfirmationStatus.URL_BLOCKED, str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - a bad candidate must not abort the run
            say(f"  {label}: download failed ({exc})")
            results.append(_skipped(candidate, social, ConfirmationStatus.DOWNLOAD_FAILED, str(exc)))
            continue

        try:
            distance = hamming(query_phash, phash(image))
            faces = engine.analyze(image)
            embeddable = [f for f in faces if f.embedding is not None]
            similarity, matched_face = best_similarity(query_embedding, embeddable)
        except Exception as exc:  # noqa: BLE001
            say(f"  {label}: analysis failed ({type(exc).__name__})")
            results.append(
                _skipped(
                    candidate, social, ConfirmationStatus.ANALYSIS_FAILED, f"analysis failed: {type(exc).__name__}"
                )
            )
            continue

        status = classify(
            face_similarity=similarity,
            embeddable_faces=len(embeddable),
            phash_distance=distance,
            cosine_threshold=cosine_threshold,
            phash_max_distance=phash_max_distance,
        )
        face_ok = len(embeddable) > 0 and _finite(similarity) and similarity >= cosine_threshold
        derivative_ok = 0 <= distance <= phash_max_distance
        confirmed = status in ConfirmationStatus.CONFIRMED

        confirmation = Confirmation(
            candidate=candidate,
            status=status,
            face_similarity=similarity if _finite(similarity) else 0.0,
            phash_distance=distance,
            faces_in_candidate=len(faces),
            embeddable_faces=len(embeddable),
            candidate_image_sha256=sha256_bytes(raw),
            candidate_image_bytes=raw if confirmed else None,
            candidate_face=matched_face if confirmed else None,
            social=social,
            face_check_passed=face_ok,
            derivative_check_passed=derivative_ok,
        )
        results.append(confirmation)

        verdict = {
            ConfirmationStatus.FACE_MATCH: "FACE MATCH ",
            ConfirmationStatus.IMAGE_DERIVATIVE: "IMG DERIV. ",
        }.get(status, "rejected   ")
        say(
            f"  {label}: {verdict} cos={fmt_score(confirmation.face_similarity)}  "
            f"pHash={distance:2d}/64  faces={len(faces)}"
            f"{'  [social]' if social else ''}"
        )

        if stop_early and confirmed and social:
            say("  stopping early on first confirmed social match")
            break

    return results


def select_best(
    confirmations: Iterable[Confirmation],
    *,
    allowed: tuple[str, ...] = ConfirmationStatus.CONFIRMED,
) -> Confirmation | None:
    """Pick the candidate to register, or ``None``. Deterministic; see module doc."""
    eligible = [c for c in confirmations if c.status in allowed]
    if not eligible:
        return None

    def key(c: Confirmation) -> tuple:
        return (
            0 if c.status == ConfirmationStatus.FACE_MATCH else 1,
            not c.social,
            -c.face_similarity,
            c.phash_distance if c.phash_distance is not None else 65,
            int(c.candidate.position),
            c.candidate.page_url,
            c.candidate.best_image_url() or "",
        )

    return min(eligible, key=key)


def score_table(confirmations: list[Confirmation], limit: int = 30) -> str:
    """Render the scores as a fixed-width table for the terminal."""
    header = f"  {'#':>2}  {'cosine':>7}  {'pHash':>6}  {'faces':>5}  {'soc':>3}  {'status':<32}  domain"
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
