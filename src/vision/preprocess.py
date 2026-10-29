"""
Image IO, perceptual hashing, safe remote fetching, and demo rendering.
"""

from __future__ import annotations

import struct
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import cv2
import numpy as np

__all__ = [
    "ImageError",
    "DownloadError",
    "UnsafeDownloadError",
    "decode_image_safely",
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
DOWNLOAD_TIMEOUT = 20  # per request; a total deadline is enforced separately
TOTAL_DEADLINE_SECONDS = 45
MAX_REDIRECTS = 3
# Decoded-image bounds: a small compressed file can expand to gigabytes.
MAX_IMAGE_DIMENSION = 16384
MAX_IMAGE_PIXELS = 50_000_000
MAX_CONCURRENT_FETCHES = 2
USER_AGENT = (
    "face-blockchain-verification/1.0 (academic image-provenance research; "
    "contact via repository)"
)

_FETCH_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_FETCHES)


class ImageError(RuntimeError):
    """An image could not be read or decoded."""


class DownloadError(RuntimeError):
    """A remote image could not be retrieved."""


class UnsafeDownloadError(DownloadError):
    """The URL (or a redirect target) was refused by the SSRF guard."""


def _sniff_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read (width, height) from a PNG/JPEG/GIF/BMP/WebP header without decoding.

    Returns ``None`` for an unrecognised format. Used to reject decompression
    bombs *before* handing bytes to the decoder.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"BM" and len(data) >= 26:
        w, h = struct.unpack("<ii", data[18:26])
        return abs(w), abs(h)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        kind = data[12:16]
        if kind == b"VP8X":
            return (
                1 + int.from_bytes(data[24:27], "little"),
                1 + int.from_bytes(data[27:30], "little"),
            )
        if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if kind == b"VP8L" and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        return None
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2 : i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return w, h
            i += 2 + length
    return None


def decode_image_safely(raw: bytes, *, label: str = "image") -> np.ndarray:
    """Decode *raw* to a validated BGR ``uint8`` array, or raise :class:`ImageError`.

    Checks, in order: non-empty, a recognised format, header dimensions within
    :data:`MAX_IMAGE_DIMENSION` / :data:`MAX_IMAGE_PIXELS` (before any pixel
    allocation), successful decode, and the decoded array's dtype and shape.
    """
    if not raw:
        raise ImageError(f"{label} is empty")
    dims = _sniff_dimensions(raw)
    if dims is None:
        raise ImageError(
            f"{label} is not a supported image format (JPEG, PNG, WebP, GIF, BMP)"
        )
    width, height = dims
    if width <= 0 or height <= 0:
        raise ImageError(f"{label} reports invalid dimensions")
    if max(width, height) > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
        raise ImageError(
            f"{label} is {width}x{height}, above the limit of "
            f"{MAX_IMAGE_DIMENSION}px per side / {MAX_IMAGE_PIXELS // 1_000_000} MP"
        )
    try:
        img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise ImageError(f"{label} could not be decoded") from exc
    if (
        img is None
        or img.dtype != np.uint8
        or img.ndim != 3
        or img.shape[2] != 3
        or img.shape[0] == 0
        or img.shape[1] == 0
    ):
        raise ImageError(f"{label} did not decode as a valid image (corrupt?)")
    return img


def load_image(path: str | Path) -> np.ndarray:
    """Read an image from disk as BGR, with size limits.

    Reads bytes in Python then decodes, rather than ``cv2.imread``, because
    ``cv2.imread`` silently returns None for non-ASCII paths on Windows.
    """
    p = Path(path)
    if not p.exists():
        raise ImageError(f"no such image: {p}")
    size = p.stat().st_size
    if size == 0:
        raise ImageError(f"image is empty: {p}")
    if size > MAX_DOWNLOAD_BYTES * 2:
        raise ImageError(f"image file is too large: {p}")
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise ImageError(f"could not read {p}: {exc.strerror or 'I/O error'}") from exc
    return decode_image_safely(raw, label=p.name)


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
    exact artefact can be hashed and archived as evidence.

    Third-party URLs are hostile input. Every hop (the first URL and each
    redirect target) is validated by :mod:`src.vision.netguard`; redirects are
    followed manually, at most :data:`MAX_REDIRECTS` times; size, time and
    content type are bounded; the decoded image is bounded too. When no
    *session* is given, a connection-pinned session is used so the connect goes
    to the address that was validated.
    """
    from .netguard import UnsafeURLError, resolve_public_addresses, validate_url

    owns_session = session is None
    if owns_session:
        from .netguard import make_guarded_session

        session = make_guarded_session()

    deadline = time.monotonic() + TOTAL_DEADLINE_SECONDS
    seen: set[str] = set()
    current = url
    raw = b""
    try:
        with _FETCH_SLOTS:
            for _hop in range(MAX_REDIRECTS + 1):
                try:
                    parsed = validate_url(current)
                    resolve_public_addresses(parsed.host, parsed.port)
                except UnsafeURLError as exc:
                    raise UnsafeDownloadError(f"refused URL: {exc}") from exc
                if current in seen:
                    raise DownloadError("redirect loop")
                seen.add(current)
                if time.monotonic() > deadline:
                    raise DownloadError("download deadline exceeded")

                try:
                    resp = session.get(
                        current,
                        timeout=DOWNLOAD_TIMEOUT,
                        stream=True,
                        allow_redirects=False,
                        headers={"User-Agent": USER_AGENT},
                    )
                except Exception as exc:  # noqa: BLE001
                    raise DownloadError(
                        f"request to {parsed.host} failed ({type(exc).__name__})"
                    ) from exc

                with resp:
                    status = resp.status_code
                    if status in (301, 302, 303, 307, 308):
                        location = resp.headers.get("Location") or ""
                        if not location:
                            raise DownloadError(f"HTTP {status} without Location")
                        current = urljoin(current, location)
                        continue
                    if status != 200:
                        raise DownloadError(f"HTTP {status}")
                    raw = _read_body(resp, deadline)
                break
            else:
                raise DownloadError(f"more than {MAX_REDIRECTS} redirects")
    finally:
        if owns_session:
            session.close()

    try:
        img = decode_image_safely(raw, label="downloaded image")
    except ImageError as exc:
        raise DownloadError(str(exc)) from exc
    return raw, img


def _read_body(resp: Any, deadline: float) -> bytes:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if ctype and not ctype.startswith(("image/", "application/octet-stream")):
        raise DownloadError(f"not an image (Content-Type: {ctype[:60]})")
    declared = resp.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
        raise DownloadError(
            f"image exceeds {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MiB limit"
        )
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
        if time.monotonic() > deadline:
            raise DownloadError("download deadline exceeded")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        raise DownloadError("empty response body")
    return raw


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
    query_face: np.ndarray | None,
    candidate_face: np.ndarray | None,
    *,
    similarity: str,
    threshold: str,
    phash_distance: int,
    matched_url: str,
    accepted: bool,
    tile: int = 224,
    verdict: str | None = None,
    candidate_caption: str = "candidate face (from the post)",
) -> np.ndarray:
    """Render the query face beside the matched face, annotated with scores.

    This is the single frame that makes the match legible to a human watching
    the recording, instead of asking them to trust a number in a JSON file.
    """
    def _fit(img: np.ndarray | None) -> np.ndarray:
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
    if verdict is None:
        verdict = "CONFIRMED MATCH" if accepted else "REJECTED (below threshold)"

    _label(canvas, "query face", (gap, 22), (200, 200, 200))
    _label(
        canvas,
        _elide(candidate_caption, tile),
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
