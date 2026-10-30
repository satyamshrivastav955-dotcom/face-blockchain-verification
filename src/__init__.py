"""
Face ID + Blockchain Verification pipeline.

Proof-of-registration system that:
- Searches the web for images matching a query face (SerpApi / TinEye / local fixture).
- Confirms each candidate locally (face cosine similarity + perceptual hash).
- Records the result in a tamper-evident JSON bundle (RFC 8785 JCS + SHA-256).
- Anchors the record hash on an EVM-compatible blockchain (Merkle-batch or per-record).
- Supports C2PA Content Credentials and geometric image-derivative verification.

Run as ``python -m src.main --help``.
See README.md and docs/ for full documentation.
"""

__version__ = "2.0.0"

# Record schema written by this build.  "faceverify/v1" records (historical) are
# still readable and verifiable; see src/evidence/record.py.
SCHEMA_VERSION = "faceverify/v2"
SUPPORTED_SCHEMAS = ("faceverify/v1", "faceverify/v2")
