"""
Image IO, perceptual hashing, safe remote fetching, and demo rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

__all__ = [
    "ImageError",
    "DownloadError",
    "load_image",
    "encode_png",
    "image_info",
    "phash",
    "phash_hex",
    "hamming",
    "fetch_image",
    "side_by_side",
]

# Guard rails for fetching third-party images we did not choose.
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
DOWNLOAD_TIMEOUT = 20
USER_AGENT = (
    "face-blockchain-verification/1.0 (academic image-provenance research; "
    "contact via repository)"
)


class ImageError(RuntimeError):
    """An image could not be read or decoded."""


class DownloadError(RuntimeError):
    """A remote image could not be retrieved."""


def load_image(path: str | Path) -> np.ndarray:
    """Read an image from disk as BGR.

    Uses ``np.fromfile`` + ``cv2.imdecode`` rather than ``cv2.imread`` because
    ``cv2.imread`` silently returns None for paths containing non-ASCII
    characters on Windows - it passes the path to the C++ layer as a narrow
    byte string. Reading the bytes in Python first sidesteps that entirely.
    """
    p = Path(path)
    if not p.exists():
        raise ImageError(f"no such image: {p}")
    if p.stat().st_size == 0:
        raise ImageError(f"image is empty: {p}")
    try:
        buf = np.fromfile(str(p), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception as exc:  # pragma: no cover - defensive
        raise ImageError(f"could not read {p}: {exc}") from exc
    if img is None:
        raise ImageError(
            f"could not decode {p} as an image (corrupt, or an unsupported format)"
        )
    return img


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ImageError("PNG encoding failed")
    return buf.tobytes()


def image_info(img: np.ndarray) -> dict[str, int]:
    h, w = img.shape[:2]
    return {"width": int(w), "height": int(h)}


def phash(img: np.ndarray, hash_size: int = 8, highfreq_factor: int = 4) -> int:
    """64-bit perceptual hash (DCT-based), returned as an int.

    Standard pHash: convert to grayscale, resize to 32x32, take the 2-D DCT,
    keep the top-left 8x8 low-frequency block, and threshold each coefficient
    against the block median.

    The DC coefficient (0,0) encodes overall brightness and is orders of
    magnitude larger than the rest; including it in the median would drag the
    threshold and waste bits. We therefore compute the median over the other
    63 coefficients while still emitting 64 bits. This differs from some
    library implementations, which is harmless here: the same function is used
    at register and verify time, so the comparison is self-consistent.
    """
    size = hash_size * highfreq_factor
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    coeffs = cv2.dct(small.astype(np.float32))
    block = coeffs[:hash_size, :hash_size]

    flat = block.flatten()
    median = float(np.median(np.delete(flat, 0)))

    bits = 0
    for value in flat:
        bits = (bits << 1) | int(float(value) > median)
    return bits


def phash_hex(img: np.ndarray) -> str:
    """Perceptual hash as a fixed-width 16-char hex string."""
    return f"{phash(img):016x}"


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two hashes (0-64 for a 64-bit hash)."""
    return int(a ^ b).bit_count()


def fetch_image(url: str, session: Any = None) -> tuple[bytes, np.ndarray]:
    """Download an image, defensively, and decode it.

    Returns ``(raw_bytes, bgr_array)``. The raw bytes are returned too so the
    exact artefact can be hashed and archived as evidence - re-encoding first
    would change the hash and weaken the audit trail.

    Third-party URLs are hostile input, so we cap the response size, cap the
    time, require an image content type when one is offered, and never follow
    a non-HTTP scheme.
    """
    import requests

    if not url.lower().startswith(("http://", "https://")):
        raise DownloadError(f"refusing non-HTTP URL: {url[:120]}")

    sess = session or requests
    try:
        resp = sess.get(
            url,
            timeout=DOWNLOAD_TIMEOUT,
            stream=True,
            headers={"User-Agent": USER_AGENT},
        )
    except Exception as exc:
        raise DownloadError(f"request failed: {exc}") from exc

    with resp:
        if resp.status_code != 200:
            raise DownloadError(f"HTTP {resp.status_code}")

        ctype = (resp.headers.get("Content-Type") or "").lower()
        if ctype and not ctype.startswith(("image/", "application/octet-stream")):
            raise DownloadError(f"not an image (Content-Type: {ctype})")

        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise DownloadError(
                    f"image exceeds {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MiB limit"
                )
            chunks.append(chunk)

    raw = b"".join(chunks)
    if not raw:
        raise DownloadError("empty response body")

    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise DownloadError("response body did not decode as an image")
    return raw, img


# ---------------------------------------------------------------------------
# Demo rendering
# ---------------------------------------------------------------------------

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_SCALE = 0.5


def _text_width(text: str, scale: float = _SCALE) -> int:
    return cv2.getTextSize(text, _FONT, scale, 1)[0][0]


def _label(canvas: np.ndarray, text: str, org: tuple[int, int], colour: tuple[int, int, int]) -> None:
    """Draw text with a dark drop shadow so it stays legible on any background.

    The shadow is drawn at the *same* thickness as the text, one pixel down and
    across, rather than as a thicker outline underneath. OpenCV's Hershey glyph
    advance grows with thickness (the same string measures 293px at thickness 1
    and 311px at thickness 3), so an outline pass drifts progressively out of
    register and leaves its tail sticking out past the end of the label.
    """
    cv2.putText(canvas, text, (org[0] + 1, org[1] + 1), _FONT, _SCALE, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(canvas, text, org, _FONT, _SCALE, colour, 1, cv2.LINE_AA)


def _elide(text: str, max_px: int) -> str:
    """Shorten text with an ellipsis until it fits ``max_px``, measured not guessed."""
    if _text_width(text) <= max_px:
        return text
    for end in range(len(text) - 1, 0, -1):
        candidate = text[:end] + "..."
        if _text_width(candidate) <= max_px:
            return candidate
    return ""


def side_by_side(
    query_face: np.ndarray,
    candidate_face: np.ndarray,
    *,
    similarity: str,
    threshold: str,
    phash_distance: int,
    matched_url: str,
    accepted: bool,
    tile: int = 224,
) -> np.ndarray:
    """Render the query face beside the matched face, annotated with scores.

    This is the single frame that makes the match legible to a human watching
    the recording, instead of asking them to trust a number in a JSON file.
    """
    def _fit(img: np.ndarray) -> np.ndarray:
        if img is None or img.size == 0:
            return np.full((tile, tile, 3), 40, dtype=np.uint8)
        return cv2.resize(img, (tile, tile), interpolation=cv2.INTER_AREA)

    left, right = _fit(query_face), _fit(candidate_face)
    gap, header, footer = 16, 34, 98
    width = tile * 2 + gap * 3
    height = header + tile + footer

    canvas = np.full((height, width, 3), 24, dtype=np.uint8)
    canvas[header : header + tile, gap : gap + tile] = left
    canvas[header : header + tile, gap * 2 + tile : gap * 2 + tile * 2] = right

    accent = (110, 220, 130) if accepted else (110, 110, 240)
    verdict = "CONFIRMED MATCH" if accepted else "REJECTED (below threshold)"

    _label(canvas, "query face", (gap, 22), (200, 200, 200))
    _label(
        canvas,
        _elide("candidate face (from the post)", tile),
        (gap * 2 + tile, 22),
        (200, 200, 200),
    )

    # Each line gets its own row, left-aligned. The matched URL in particular
    # used to share a row and ran off the right edge of the canvas - which
    # truncated the one field a human reader most needs to see.
    y = header + tile + 22
    inner = width - gap * 2
    _label(canvas, f"cosine similarity {similarity}  (threshold {threshold})", (gap, y), accent)
    _label(canvas, f"pHash Hamming distance {phash_distance}/64", (gap, y + 20), (200, 200, 200))
    _label(canvas, verdict, (gap, y + 40), accent)
    _label(canvas, _elide(matched_url, inner), (gap, y + 62), (190, 190, 190))

    cv2.rectangle(canvas, (gap - 2, header - 2), (gap + tile + 1, header + tile + 1), (90, 90, 90), 1)
    cv2.rectangle(
        canvas,
        (gap * 2 + tile - 2, header - 2),
        (gap * 2 + tile * 2 + 1, header + tile + 1),
        accent,
        2,
    )
    return canvas
