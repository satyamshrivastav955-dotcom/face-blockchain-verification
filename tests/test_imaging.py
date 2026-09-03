"""
Perceptual hashing and image handling.

The pHash is the second, independent opinion in the confirmation rule, so it
has to be both *stable* under the transformations social platforms apply and
*discriminating* between genuinely different images. Both properties are
asserted here rather than assumed.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.imaging import (
    ImageError,
    DownloadError,
    encode_png,
    fetch_image,
    hamming,
    image_info,
    load_image,
    phash,
    phash_hex,
    side_by_side,
)

from conftest import make_blob, make_stripes, rewrite, write_png


class TestPHashInvariance:
    """Distance stays small when the picture is still the same picture."""

    def test_identical_images_hash_identically(self):
        img = make_blob()
        assert phash(img) == phash(img.copy())
        assert hamming(phash(img), phash(img.copy())) == 0

    def test_survives_rescale_and_jpeg(self):
        img = make_blob()
        distance = hamming(phash(img), phash(rewrite(img)))
        assert distance <= 12, f"a re-encoded copy scored {distance}/64"

    def test_survives_brightness_shift(self):
        img = make_blob()
        brighter = np.clip(img.astype(np.int32) + 25, 0, 255).astype(np.uint8)
        assert hamming(phash(img), phash(brighter)) <= 12

    def test_survives_mild_blur(self):
        import cv2

        img = make_blob()
        blurred = cv2.GaussianBlur(img, (5, 5), 0)
        assert hamming(phash(img), phash(blurred)) <= 12

    def test_size_independent(self):
        import cv2

        img = make_blob(size=256)
        small = cv2.resize(img, (96, 96), interpolation=cv2.INTER_AREA)
        assert hamming(phash(img), phash(small)) <= 12


class TestPHashDiscrimination:
    """Distance is large when the pictures genuinely differ."""

    def test_unrelated_images_are_far_apart(self):
        distance = hamming(phash(make_blob()), phash(make_stripes()))
        assert distance > 12, f"unrelated images scored only {distance}/64"

    def test_moved_subject_changes_the_hash(self):
        a = phash(make_blob(cx=0.30, cy=0.30))
        b = phash(make_blob(cx=0.70, cy=0.70))
        assert hamming(a, b) > 0


class TestPHashMechanics:
    def test_is_64_bits(self):
        value = phash(make_blob())
        assert 0 <= value < 2**64

    def test_hex_is_fixed_width(self):
        text = phash_hex(make_blob())
        assert len(text) == 16
        assert int(text, 16) == phash(make_blob())

    def test_accepts_grayscale_input(self):
        import cv2

        img = make_blob()
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        assert isinstance(phash(gray), int)

    def test_dc_coefficient_excluded_from_median(self):
        """A flat image must not produce an all-ones hash.

        Including the huge DC term in the median would drag the threshold and
        waste bits; this is the observable consequence of excluding it.
        """
        flat = np.full((64, 64, 3), 128, dtype=np.uint8)
        value = phash(flat)
        assert value not in (0, 2**64 - 1)


class TestHamming:
    def test_known_values(self):
        assert hamming(0, 0) == 0
        assert hamming(0b1011, 0b1001) == 1
        assert hamming(0, 2**64 - 1) == 64

    def test_symmetric(self):
        a, b = phash(make_blob()), phash(make_stripes())
        assert hamming(a, b) == hamming(b, a)


class TestLoadImage:
    def test_round_trip(self, tmp_path):
        path = write_png(tmp_path / "x.png", make_blob())
        img = load_image(path)
        assert img.shape == (256, 256, 3)
        assert image_info(img) == {"width": 256, "height": 256}

    def test_non_ascii_path(self, tmp_path):
        """cv2.imread returns None here on Windows; load_image must not."""
        path = write_png(tmp_path / "photo_café_日本.png", make_blob())
        assert load_image(path).size > 0

    def test_missing_file(self, tmp_path):
        with pytest.raises(ImageError):
            load_image(tmp_path / "nope.png")

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.png"
        path.write_bytes(b"")
        with pytest.raises(ImageError):
            load_image(path)

    def test_not_an_image(self, tmp_path):
        path = tmp_path / "notes.png"
        path.write_bytes(b"this is plainly not a PNG")
        with pytest.raises(ImageError):
            load_image(path)

    def test_encode_png_round_trip(self, tmp_path):
        img = make_blob()
        path = tmp_path / "enc.png"
        path.write_bytes(encode_png(img))
        assert np.array_equal(load_image(path), img)


class TestFetchImageGuards:
    def test_rejects_non_http_scheme(self):
        # No network needed: the scheme check happens before any request, which
        # is the point - a file:// URL from a hostile response must not be read.
        with pytest.raises(DownloadError):
            fetch_image("file:///etc/passwd")
        with pytest.raises(DownloadError):
            fetch_image("ftp://example.com/x.png")


class TestSideBySide:
    def test_renders_with_both_faces(self):
        canvas = side_by_side(
            make_blob(112),
            make_blob(112, cx=0.5),
            similarity="0.7412",
            threshold="0.3630",
            phash_distance=4,
            matched_url="https://x.com/user/status/1",
            accepted=True,
        )
        assert canvas.ndim == 3 and canvas.shape[2] == 3
        assert canvas.shape[0] > 224 and canvas.shape[1] > 448

    def test_tolerates_a_missing_candidate_face(self):
        canvas = side_by_side(
            make_blob(112),
            None,
            similarity="0.1000",
            threshold="0.3630",
            phash_distance=40,
            matched_url="https://example.com/",
            accepted=False,
        )
        assert canvas.size > 0

    def test_a_long_url_is_elided_to_fit(self):
        """The matched URL is the field a human most needs; it must not run off."""
        from src.imaging import _elide, _text_width

        url = "https://www.instagram.com/p/C8xYzAbCdEf/?img_index=2&utm_source=ig_web&x=y"
        canvas = side_by_side(
            make_blob(112),
            make_blob(112),
            similarity="0.9000",
            threshold="0.3630",
            phash_distance=2,
            matched_url=url,
            accepted=True,
        )
        inner = canvas.shape[1] - 32
        assert _text_width(_elide(url, inner)) <= inner
        assert _elide(url, inner).endswith("...")
        assert _elide("https://x.com/a/status/1", inner) == "https://x.com/a/status/1"

    def test_labels_do_not_bleed_off_the_canvas(self):
        """A drop shadow keeps its glyph metrics; a thick outline does not.

        OpenCV's Hershey advance widens with thickness, so drawing an outline
        pass at thickness 3 under text at thickness 1 leaves the outline's tail
        protruding. Guard: nothing may be drawn in the last two columns.
        """
        canvas = side_by_side(
            make_blob(112),
            make_blob(112),
            similarity="1.0000",
            threshold="0.3630",
            phash_distance=8,
            matched_url="https://x.com/demo_user/status/1799887766554433221",
            accepted=True,
        )
        right_edge = canvas[:, -2:, :]
        assert int(right_edge.max()) <= 40, "something was drawn against the right edge"
