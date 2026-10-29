"""
Consent gates and local evidence retention.

Two operations send the user's photo (or a link to it) to someone else:

* **public upload** - ``publish_image`` puts the query image on a third-party
  public host so a URL-only search engine can fetch it;
* **external search** - the search provider receives the image (TinEye) or a
  public URL to it (SerpApi/Google Lens).

Neither is "ordinary local computation", so neither runs unless the caller
passes an explicit consent flag. Local-only work (face analysis, hashing, the
offline fixture provider, simulated chain, local verification) needs none.

This module deliberately promises nothing about what a third party does with
the data afterwards (retention, deletion, indexing): that is governed by their
terms, which this project does not control. It only states what is *sent*.
"""

from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ConsentError",
    "DataDisclosure",
    "disclosure_for",
    "require_consent",
    "purge_evidence",
]


class ConsentError(RuntimeError):
    """An external-processing step was requested without explicit consent."""


@dataclass(frozen=True)
class DataDisclosure:
    service: str
    what_is_sent: str
    flag: str


_SEARCH_SENDS = {
    "serpapi_google_lens": (
        "SerpApi (serpapi.com) and, through it, Google Lens",
        "a public URL of your query image (Google Lens downloads the image from that URL), plus your SerpApi API key",
    ),
    "tineye": (
        "TinEye (api.tineye.com)",
        "the full query image file, plus your TinEye API key",
    ),
}

_PUBLISH_SENDS = {
    "catbox": "catbox.moe (falling back to uguu.se if it fails): the full image file, publicly reachable",
    "uguu": "uguu.se: the full image file, publicly reachable",
    "imgbb": "imgbb.com: the full image file, publicly reachable, plus your IMGBB_API_KEY",
}


def disclosure_for(
    provider_name: str, *, needs_public_url: bool, publish_provider: str, have_image_url: bool
) -> list[DataDisclosure]:
    """What would leave this machine for the given configuration."""
    items: list[DataDisclosure] = []
    key = (publish_provider or "none").lower()
    if needs_public_url and not have_image_url and key in _PUBLISH_SENDS:
        # With PUBLISH_PROVIDER=none nothing is uploaded: the pipeline stops with
        # an actionable message instead (pass --image-url or configure a host).
        items.append(DataDisclosure("public image host", _PUBLISH_SENDS[key], "--consent-public-upload"))
    service, sent = _SEARCH_SENDS.get(provider_name, (provider_name, "the query image or a URL to it"))
    items.append(DataDisclosure(service, sent, "--consent-external-search"))
    return items


def require_consent(
    *,
    provider_name: str,
    is_offline_stub: bool,
    needs_public_url: bool,
    publish_provider: str,
    have_image_url: bool,
    consent_external_search: bool,
    consent_public_upload: bool,
) -> list[DataDisclosure]:
    """Raise :class:`ConsentError` unless every needed consent was given.

    Returns the disclosures that apply (empty for offline providers).
    """
    if is_offline_stub:
        return []
    items = disclosure_for(
        provider_name,
        needs_public_url=needs_public_url,
        publish_provider=publish_provider,
        have_image_url=have_image_url,
    )
    missing = []
    for item in items:
        granted = consent_public_upload if item.flag == "--consent-public-upload" else consent_external_search
        if not granted:
            missing.append(item)
    if missing:
        lines = ["this step sends data to a third party and needs your explicit consent:"]
        for item in missing:
            lines.append(f"  - {item.service}: {item.what_is_sent}  (pass {item.flag})")
        lines.append(
            "nothing has been sent. For a local-only test run use "
            "--fixture <file> --allow-offline-stub --engine stub --dry-run."
        )
        raise ConsentError("\n".join(lines))
    return items


# ---------------------------------------------------------------------------
# Evidence retention
# ---------------------------------------------------------------------------

_RUN_DIR = re.compile(r"^\d{8}T\d{6}Z(_[0-9a-f]{1,8})?$")


def purge_evidence(evidence_dir: Path, *, older_than_days: float, dry_run: bool = True) -> list[Path]:
    """Delete evidence run directories older than *older_than_days*.

    Only directories named like a run id (``YYYYMMDDTHHMMSSZ[_hash]``) directly
    inside *evidence_dir* are considered; symlinks and anything else are left
    alone. ``dry_run`` (the default) only reports. The *record* file written to
    ``output/`` is never touched - only the supporting evidence bundle.
    """
    if older_than_days < 0:
        raise ValueError("older_than_days must be >= 0")
    root = Path(evidence_dir)
    if not root.is_dir():
        return []
    cutoff = time.time() - older_than_days * 86400
    removed: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_symlink() or not child.is_dir() or not _RUN_DIR.match(child.name):
            continue
        if child.stat().st_mtime > cutoff:
            continue
        removed.append(child)
        if not dry_run:
            shutil.rmtree(child)
    return removed
