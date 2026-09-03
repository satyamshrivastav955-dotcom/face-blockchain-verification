"""
Publishing the query image so URL-only search engines can fetch it.

Google Lens (via SerpApi) accepts the query image as a URL, not an upload, so a
local file has to be reachable publicly for the duration of the search. This
module handles that and nothing else.

PRIVACY NOTE
============
This step puts the query image on a third-party host. Only ever run it on an
image you have the right to publish - your own photo, or an openly licensed
one. If that is not acceptable for a given image, set ``PUBLISH_PROVIDER=none``
and use the TinEye backend, which uploads directly to the search API instead,
or pass ``--image-url`` for a host you control.
"""

from __future__ import annotations

import base64
from pathlib import Path

__all__ = ["PublishError", "publish_image", "PUBLISHERS"]

PUBLISHERS = ("catbox", "uguu", "imgbb", "none")
TIMEOUT = 90


class PublishError(RuntimeError):
    """The image could not be made publicly reachable."""


def _publish_uguu(path: Path) -> str:
    """Upload to uguu.se. Free, no API key required."""
    import requests

    with path.open("rb") as fh:
        resp = requests.post(
            "https://uguu.se/upload",
            files={"files[]": (path.name, fh)},
            timeout=TIMEOUT,
        )
    if resp.status_code != 200:
        raise PublishError(f"uguu returned HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
    except Exception as exc:
        raise PublishError("uguu response was not JSON") from exc
    files = data.get("files")
    if not files or not isinstance(files, list):
        raise PublishError(f"uguu returned no files in response: {data}")
    url = files[0].get("url")
    if not url:
        raise PublishError(f"uguu file entry had no url: {files[0]}")
    return str(url)


def _publish_catbox(path: Path) -> str:
    """Upload to catbox.moe with automatic fallback to uguu.se. No API key required."""
    import requests

    try:
        with path.open("rb") as fh:
            resp = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (path.name, fh)},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=TIMEOUT,
            )
        if resp.status_code == 200:
            url = resp.text.strip()
            if url.startswith("http"):
                return url
    except Exception:
        pass
    # Fallback to uguu.se if catbox blocks or fails
    return _publish_uguu(path)


def _publish_imgbb(path: Path, api_key: str) -> str:
    """Upload to imgbb. Needs a free API key."""
    import requests

    if not api_key:
        raise PublishError("IMGBB_API_KEY is not set")
    payload = base64.b64encode(path.read_bytes())
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        params={"key": api_key},
        data={"image": payload},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise PublishError(f"imgbb returned HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise PublishError("imgbb response was not JSON") from exc
    url = ((data.get("data") or {}).get("url")) if isinstance(data, dict) else None
    if not url:
        raise PublishError(f"imgbb response had no image URL: {str(data)[:200]}")
    return str(url)


def publish_image(path: str | Path, provider: str, *, imgbb_api_key: str = "") -> str:
    """Make *path* publicly reachable and return its URL."""
    p = Path(path)
    if not p.exists():
        raise PublishError(f"no such image: {p}")

    key = (provider or "").strip().lower()
    if key in ("none", "", "manual"):
        raise PublishError(
            "PUBLISH_PROVIDER is 'none', so the image was not uploaded. Pass "
            "--image-url with a publicly reachable URL, or set PUBLISH_PROVIDER "
            "to catbox, uguu, or imgbb."
        )
    if key in ("catbox", "auto", "free"):
        return _publish_catbox(p)
    if key == "uguu":
        return _publish_uguu(p)
    if key == "imgbb":
        return _publish_imgbb(p, imgbb_api_key)
    raise PublishError(
        f"unknown publish provider {provider!r}. Available: {', '.join(PUBLISHERS)}"
    )
