"""Evidence subsystem: canonical hashing, records, and evidence bundles."""

from .bundle import EvidenceBundle, new_run_id
from .hashing import (
    CanonicalizationError,
    canonicalize,
    digest,
    digest_hex,
    fmt_score,
    sha256_bytes,
    sha256_file,
)
from .record import (
    INTEGRITY_ALGORITHM,
    LocalCheck,
    Status,
    attach_anchor,
    build_payload,
    check_local_integrity,
    load_record,
    mutate_payload,
    save_record,
    seal,
    utc_now,
)

__all__ = [
    "CanonicalizationError",
    "EvidenceBundle",
    "INTEGRITY_ALGORITHM",
    "LocalCheck",
    "Status",
    "attach_anchor",
    "build_payload",
    "canonicalize",
    "check_local_integrity",
    "digest",
    "digest_hex",
    "fmt_score",
    "load_record",
    "mutate_payload",
    "new_run_id",
    "save_record",
    "seal",
    "sha256_bytes",
    "sha256_file",
    "utc_now",
]
