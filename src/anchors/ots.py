"""
OpenTimestamps (OTS) anchoring: prove a record's hash existed no later than a Bitcoin block.

WHAT THIS PROVES, AND WHAT IT DOES NOT
======================================
* It proves ONE thing: the 32-byte record hash existed before the timestamp of a specific Bitcoin
  block. That is all an on-chain registry of the same hash would prove too, without a wallet, gas,
  a contract to trust or a testnet that may be retired.
* It does NOT prove who submitted the hash (use the record signature for that), nor that the claim
  inside the record is true, nor when the image was created.
* A fresh stamp is ``pending``: calendar servers aggregate hashes and publish a Bitcoin transaction
  within hours. Until ``upgrade`` fetches the Bitcoin attestation the record is NOT anchored, and
  verification says so (it never reports a pending stamp as success).

PRIVACY
=======
Only the SHA-256 record hash goes to the calendar servers (never the image, a face, a URL or the
record). Submission is a network call to third parties and is therefore opt-in at the CLI.

TRUST ASSUMPTIONS OF VERIFICATION
=================================
The Bitcoin block header is fetched from block explorers (Blockstream / mempool.space style HTTP
APIs). Checking the Merkle path locally is exact, but the header itself is taken from those
services; with two explorers configured they must agree. For full independence verify the same
``.ots`` proof with ``ots verify`` against your own Bitcoin node.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DEFAULT_CALENDARS = (
    "https://alice.btc.calendar.opentimestamps.org",
    "https://bob.btc.calendar.opentimestamps.org",
    "https://finney.calendar.eternitywall.com",
)
DEFAULT_EXPLORERS = ("https://blockstream.info/api", "https://mempool.space/api")

MAX_OTS_BYTES = 64 * 1024
CALENDAR_TIMEOUT = 15
EXPLORER_TIMEOUT = 15

HeaderFetcher = Callable[[int], bytes]


class OtsError(RuntimeError):
    """The OpenTimestamps step could not be completed."""


def _lib():
    try:
        from opentimestamps.core import notary, op, serialize, timestamp
    except ImportError as exc:  # pragma: no cover
        raise OtsError("the 'opentimestamps' package is not installed (pip install opentimestamps)") from exc
    return notary, op, serialize, timestamp


def _calendar_cls():
    from opentimestamps.calendar import RemoteCalendar

    return RemoteCalendar


def _serialise(detached: Any) -> bytes:
    _, _, serialize, _ = _lib()
    ctx = serialize.BytesSerializationContext()
    detached.serialize(ctx)
    return ctx.getbytes()


def _deserialise(raw: bytes) -> Any:
    _, _, serialize, timestamp = _lib()
    if len(raw) > MAX_OTS_BYTES:
        raise OtsError("OTS proof is larger than the allowed size")
    ctx = serialize.BytesDeserializationContext(raw)
    detached = timestamp.DetachedTimestampFile.deserialize(ctx)
    return detached


def _anchor_dict(detached: Any, digest: bytes, calendars: list[str], status: str) -> dict[str, Any]:
    return {
        "mode": "opentimestamps",
        "status": status,
        "digest": digest.hex(),
        "calendars": calendars,
        "ots": base64.b64encode(_serialise(detached)).decode("ascii"),
        "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def submit_digest(
    verification_hash: str,
    calendars: tuple[str, ...] | list[str] = DEFAULT_CALENDARS,
    *,
    calendar_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Submit the record hash to the calendars and return a ``pending`` anchor block.

    Needs at least one calendar to answer. Raises :class:`OtsError` otherwise.
    """
    _, op, _, timestamp = _lib()
    digest = bytes.fromhex(verification_hash.removeprefix("0x"))
    if len(digest) != 32:
        raise OtsError("verification hash must be 32 bytes")
    factory = calendar_factory or _calendar_cls()
    merged = timestamp.Timestamp(digest)
    used: list[str] = []
    problems: list[str] = []
    for url in calendars:
        try:
            merged.merge(factory(url).submit(digest, timeout=CALENDAR_TIMEOUT))
            used.append(url)
        except Exception as exc:  # noqa: BLE001 - one calendar being down is expected
            problems.append(f"{url}: {type(exc).__name__}")
    if not used:
        raise OtsError("no OpenTimestamps calendar accepted the digest (" + "; ".join(problems)[:300] + ")")
    detached = timestamp.DetachedTimestampFile(op.OpSHA256(), merged)
    # The file digest of a DetachedTimestampFile is the stamped message itself.
    return _anchor_dict(detached, digest, used, "pending")


def _walk(ts: Any):
    """Yield every Timestamp node in the tree (a node holds attestations and/or ops)."""
    yield ts
    for child in ts.ops.values():
        yield from _walk(child)


def upgrade_anchor(
    anchor: dict[str, Any],
    *,
    calendar_factory: Callable[[str], Any] | None = None,
) -> tuple[dict[str, Any], int]:
    """Ask the calendars for Bitcoin attestations of any pending leaves. Returns (new anchor, upgraded count).

    Only calendars on the library's whitelist are contacted (the URL inside a proof is untrusted data).
    """
    notary, _, _, _ = _lib()
    from opentimestamps.calendar import DEFAULT_CALENDAR_WHITELIST, CommitmentNotFoundError

    factory = calendar_factory or _calendar_cls()
    detached = _deserialise(_decode(anchor))
    upgraded = 0
    for node in list(_walk(detached.timestamp)):
        for att in list(node.attestations):
            if not isinstance(att, notary.PendingAttestation):
                continue
            uri = att.uri
            if calendar_factory is None and uri not in DEFAULT_CALENDAR_WHITELIST:
                continue
            try:
                node.merge(factory(uri).get_timestamp(node.msg, timeout=CALENDAR_TIMEOUT))
                upgraded += 1
            except (CommitmentNotFoundError, KeyError):
                continue  # not yet in a Bitcoin block
            except Exception:  # noqa: BLE001 - network trouble: leave it pending
                continue
    status = "bitcoin_attested" if _has_bitcoin(detached.timestamp) else "pending"
    new = dict(anchor)
    new.update({"ots": base64.b64encode(_serialise(detached)).decode("ascii"), "status": status})
    return new, upgraded


def _has_bitcoin(ts: Any) -> bool:
    notary, _, _, _ = _lib()
    return any(isinstance(a, notary.BitcoinBlockHeaderAttestation) for _, a in ts.all_attestations())


def _decode(anchor: dict[str, Any]) -> bytes:
    try:
        return base64.b64decode(str(anchor.get("ots", "")), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OtsError("anchor.ots is not valid base64") from exc


@dataclass
class OtsCheck:
    """state: bitcoin | pending | fail | error."""

    state: str
    detail: str = ""
    block_height: int | None = None
    block_time: int | None = None
    pending_calendars: list[str] = field(default_factory=list)


def explorer_header_fetcher(
    explorers: tuple[str, ...] | list[str] = DEFAULT_EXPLORERS, session: Any = None
) -> HeaderFetcher:
    """Return a function height -> 80-byte block header, cross-checking every reachable explorer.

    If two explorers answer they must agree; if none answers an :class:`OtsError` is raised.
    """
    import requests

    sess = session or requests.Session()
    sess.trust_env = False

    def fetch(height: int) -> bytes:
        got: dict[str, bytes] = {}
        problems: list[str] = []
        for base in explorers:
            base = base.rstrip("/")
            try:
                r = sess.get(f"{base}/block-height/{int(height)}", timeout=EXPLORER_TIMEOUT)
                r.raise_for_status()
                block_hash = r.text.strip()
                if len(block_hash) != 64 or any(c not in "0123456789abcdef" for c in block_hash):
                    raise ValueError("unexpected block hash")
                h = sess.get(f"{base}/block/{block_hash}/header", timeout=EXPLORER_TIMEOUT)
                h.raise_for_status()
                header = bytes.fromhex(h.text.strip())
                if len(header) != 80:
                    raise ValueError("unexpected header length")
                got[base] = header
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{base}: {type(exc).__name__}")
        if not got:
            raise OtsError("no block explorer answered (" + "; ".join(problems)[:300] + ")")
        if len(set(got.values())) > 1:
            raise OtsError("block explorers disagree about the header at height %d" % height)
        return next(iter(got.values()))

    return fetch


def check_ots_anchor(
    anchor: dict[str, Any],
    verification_hash: str,
    *,
    header_fetcher: HeaderFetcher | None = None,
) -> OtsCheck:
    """Check an ``opentimestamps`` anchor block against the (recomputed) record hash.

    * the proof must stamp exactly this hash;
    * a Bitcoin attestation's Merkle path is recomputed locally and compared with the block header;
    * a proof with only pending attestations returns ``pending`` (NOT success);
    * an unreachable explorer returns ``error`` (inconclusive), never a guess.
    """
    notary, _, _, _ = _lib()
    try:
        detached = _deserialise(_decode(anchor))
    except OtsError as exc:
        return OtsCheck("fail", str(exc))
    except Exception as exc:  # noqa: BLE001 - malformed proof bytes
        return OtsCheck("fail", f"unreadable OTS proof ({type(exc).__name__})")

    expected = bytes.fromhex(verification_hash.removeprefix("0x"))
    if detached.file_digest != expected or detached.timestamp.msg != expected:
        return OtsCheck("fail", "the OTS proof stamps a different digest than this record's hash")

    bitcoin = [
        (m, a) for m, a in detached.timestamp.all_attestations() if isinstance(a, notary.BitcoinBlockHeaderAttestation)
    ]
    pending = sorted(
        {a.uri for _, a in detached.timestamp.all_attestations() if isinstance(a, notary.PendingAttestation)}
    )
    if not bitcoin:
        if pending:
            return OtsCheck(
                "pending",
                "stamped, but not yet confirmed in a Bitcoin block (run 'ots-upgrade' in a few hours)",
                pending_calendars=pending,
            )
        return OtsCheck("fail", "the OTS proof contains no usable attestation")

    fetch = header_fetcher or explorer_header_fetcher()
    from bitcoin.core import CBlockHeader

    best: OtsCheck | None = None
    errors: list[str] = []
    for msg, att in sorted(bitcoin, key=lambda t: t[1].height):
        try:
            header = CBlockHeader.deserialize(fetch(att.height))
            block_time = att.verify_against_blockheader(msg, header)
        except OtsError as exc:
            errors.append(str(exc))
            continue
        except Exception as exc:  # noqa: BLE001 - VerificationError and malformed headers
            return OtsCheck(
                "fail", f"Bitcoin attestation at height {att.height} does not verify ({type(exc).__name__})"
            )
        if best is None or block_time < (best.block_time or block_time):
            best = OtsCheck(
                "bitcoin",
                f"hash existed by Bitcoin block {att.height}",
                block_height=att.height,
                block_time=int(block_time),
            )
    if best is not None:
        return best
    return OtsCheck("error", "; ".join(errors)[:300] or "could not fetch a Bitcoin block header")
