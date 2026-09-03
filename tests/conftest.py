"""
Shared fixtures.

The suite runs with **no network, no API keys and no ONNX weights**, which is a
deliberate design constraint: a test that needs a paid search API is a test
nobody runs. Anything that would reach the outside world is exercised through
the offline substitutes - ``StubFaceEngine``, ``LocalFixtureProvider`` and
``MockChainClient`` - all of which the CLI refuses to use without an explicit
flag, so the substitutes cannot leak into a real run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

# Import the package from the repository root regardless of where pytest is
# invoked from.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from src.config import Settings  # noqa: E402


# ---------------------------------------------------------------------------
# synthetic imagery
# ---------------------------------------------------------------------------


def make_blob(size: int = 256, cx: float = 0.42, cy: float = 0.45, radius: float = 0.30) -> np.ndarray:
    """A smooth radial blob on a gradient: the stand-in for a 'face'.

    Deterministic, structured, and low-frequency, so both the stub embedder and
    the DCT perceptual hash produce stable, meaningful values.

    The amplitudes are chosen so the result never reaches 0 or 255. That is not
    cosmetic: a clipped image loses low-frequency structure when it is
    brightened, which would make the pHash brightness-invariance test fail for
    reasons that have nothing to do with the hash. Peak grey here is ~192.
    """
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32) / size
    field = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * radius**2)))
    background = 0.18 + 0.22 * ys
    gray = np.clip(background + 0.45 * field, 0, 1) * 255
    img = cv2.cvtColor(gray.astype(np.uint8), cv2.COLOR_GRAY2BGR)
    img[:, :, 2] = np.clip(img[:, :, 2].astype(np.int32) + 18, 0, 255).astype(np.uint8)
    return img


def make_stripes(size: int = 256, period: int = 16) -> np.ndarray:
    """An unrelated high-frequency pattern - the negative control."""
    xs = np.arange(size)
    row = ((xs // period) % 2 * 200 + 30).astype(np.uint8)
    gray = np.tile(row, (size, 1))
    gray[:: period * 2, :] = 255
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def rewrite(img: np.ndarray, *, scale: float = 0.85, brightness: int = 12, quality: int = 82) -> np.ndarray:
    """Rescale, brighten and JPEG-recompress an image.

    Approximates what a social platform does to an uploaded photo, which is
    exactly the transformation the matcher has to survive.
    """
    h, w = img.shape[:2]
    out = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    out = np.clip(out.astype(np.int32) + brightness, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def write_png(path: Path, img: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", img)
    assert ok, "failed to encode test image"
    path.write_bytes(buf.tobytes())
    return path


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings rooted in a temp dir so no test writes into the repository."""
    s = Settings()
    s.root = tmp_path
    s.search_provider = "local_fixture"
    s.chain_name = "test-chain"
    s.chain_id = 84532
    s.face_cosine_threshold = 0.363
    s.phash_max_distance = 12
    s.max_candidates = 25
    return s


@pytest.fixture
def query_image(tmp_path: Path) -> Path:
    return write_png(tmp_path / "input" / "query.png", make_blob())


@pytest.fixture
def scene(tmp_path: Path, query_image: Path) -> dict:
    """A query image plus two candidates: one genuine derivative, one unrelated.

    Returns the paths and a fixture file wiring them to plausible page URLs -
    one on a social domain, one not.
    """
    original = cv2.imdecode(np.fromfile(str(query_image), dtype=np.uint8), cv2.IMREAD_COLOR)

    match_path = write_png(tmp_path / "candidates" / "match.png", rewrite(original))
    other_path = write_png(tmp_path / "candidates" / "other.png", make_stripes())

    fixture_path = tmp_path / "candidates" / "fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "page_url": "https://example.org/gallery/unrelated",
                        "image_url": str(other_path),
                        "title": "an unrelated page",
                        "source": "example.org",
                    },
                    {
                        "page_url": "https://x.com/testuser/status/1234567890",
                        "image_url": str(match_path),
                        "title": "the genuine post",
                        "source": "x.com",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "query": query_image,
        "match": match_path,
        "other": other_path,
        "fixture": fixture_path,
    }
