"""Face ID + Blockchain Verification pipeline."""

__version__ = "1.1.0"

# Record schema written by this build. "faceverify/v1" records (historical) are
# still readable and verifiable; see src/evidence/record.py.
SCHEMA_VERSION = "faceverify/v2"
SUPPORTED_SCHEMAS = ("faceverify/v1", "faceverify/v2")
