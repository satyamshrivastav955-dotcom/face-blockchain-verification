"""OpenTimestamps anchor: offline tests with fake calendars and a fake block-header source."""

from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("opentimestamps")

from bitcoin.core import CBlockHeader  # noqa: E402
from opentimestamps.core import notary, op  # noqa: E402
from opentimestamps.core.timestamp import Timestamp  # noqa: E402

from src.anchors import ots  # noqa: E402

RECORD_HASH = "0x" + hashlib.sha256(b"a record").hexdigest()
DIGEST = bytes.fromhex(RECORD_HASH[2:])


class FakeCalendar:
    """Pending on submit; becomes a Bitcoin attestation after `confirm()`."""

    confirmed: dict[bytes, tuple[int, bytes]] = {}

    def __init__(self, url: str) -> None:
        self.url = url

    def submit(self, digest: bytes, timeout=None) -> Timestamp:
        ts = Timestamp(digest)
        stamped = ts.ops.add(op.OpAppend(b"nonce")).ops.add(op.OpSHA256())
        stamped.attestations.add(notary.PendingAttestation(self.url))
        return ts

    def get_timestamp(self, commitment: bytes, timeout=None) -> Timestamp:
        if commitment not in self.confirmed:
            raise KeyError("not yet")
        height, _root = self.confirmed[commitment]
        ts = Timestamp(commitment)
        ts.attestations.add(notary.BitcoinBlockHeaderAttestation(height))
        return ts


def _header_for(root: bytes, time: int = 1_700_000_000) -> bytes:
    return CBlockHeader(
        nVersion=4, hashPrevBlock=b"\x00" * 32, hashMerkleRoot=root, nTime=time, nBits=0x1D00FFFF, nNonce=7
    ).serialize()


def _pending_commitment(anchor: dict) -> bytes:
    detached = ots._deserialise(ots._decode(anchor))
    return next(m for m, a in detached.timestamp.all_attestations() if isinstance(a, notary.PendingAttestation))


@pytest.fixture(autouse=True)
def _reset():
    FakeCalendar.confirmed = {}
    yield


def test_submit_returns_pending_anchor():
    anchor = ots.submit_digest(RECORD_HASH, ["https://cal.example"], calendar_factory=FakeCalendar)
    assert anchor["mode"] == "opentimestamps" and anchor["status"] == "pending"
    assert anchor["digest"] == DIGEST.hex()
    assert anchor["calendars"] == ["https://cal.example"]


def test_pending_is_never_success():
    anchor = ots.submit_digest(RECORD_HASH, ["https://cal.example"], calendar_factory=FakeCalendar)
    check = ots.check_ots_anchor(anchor, RECORD_HASH, header_fetcher=lambda h: pytest.fail("no header needed"))
    assert check.state == "pending"
    assert check.pending_calendars == ["https://cal.example"]


def test_no_calendar_answering_is_an_error():
    class Down:
        def __init__(self, url):
            pass

        def submit(self, *a, **k):
            raise OSError("down")

    with pytest.raises(ots.OtsError):
        ots.submit_digest(RECORD_HASH, ["https://a.example", "https://b.example"], calendar_factory=Down)


def test_upgrade_then_verify_against_header():
    anchor = ots.submit_digest(RECORD_HASH, ["https://cal.example"], calendar_factory=FakeCalendar)
    commitment = _pending_commitment(anchor)
    # Without confirmation nothing upgrades.
    same, n = ots.upgrade_anchor(anchor, calendar_factory=FakeCalendar)
    assert n == 0 and same["status"] == "pending"

    FakeCalendar.confirmed[commitment] = (800_000, commitment)
    upgraded, n = ots.upgrade_anchor(anchor, calendar_factory=FakeCalendar)
    assert n == 1 and upgraded["status"] == "bitcoin_attested"

    # The block's Merkle root is the commitment itself (a one-leaf block), as in a real proof's last step.
    check = ots.check_ots_anchor(upgraded, RECORD_HASH, header_fetcher=lambda h: _header_for(commitment))
    assert check.state == "bitcoin"
    assert check.block_height == 800_000
    assert check.block_time == 1_700_000_000


def test_wrong_header_fails():
    anchor = ots.submit_digest(RECORD_HASH, ["https://cal.example"], calendar_factory=FakeCalendar)
    commitment = _pending_commitment(anchor)
    FakeCalendar.confirmed[commitment] = (800_000, commitment)
    upgraded, _ = ots.upgrade_anchor(anchor, calendar_factory=FakeCalendar)
    check = ots.check_ots_anchor(upgraded, RECORD_HASH, header_fetcher=lambda h: _header_for(b"\x11" * 32))
    assert check.state == "fail"


def test_proof_for_a_different_hash_fails():
    anchor = ots.submit_digest(RECORD_HASH, ["https://cal.example"], calendar_factory=FakeCalendar)
    other = "0x" + hashlib.sha256(b"another record").hexdigest()
    assert ots.check_ots_anchor(anchor, other).state == "fail"


def test_unreachable_explorer_is_inconclusive_not_fail():
    anchor = ots.submit_digest(RECORD_HASH, ["https://cal.example"], calendar_factory=FakeCalendar)
    commitment = _pending_commitment(anchor)
    FakeCalendar.confirmed[commitment] = (800_000, commitment)
    upgraded, _ = ots.upgrade_anchor(anchor, calendar_factory=FakeCalendar)

    def down(height: int) -> bytes:
        raise ots.OtsError("no block explorer answered")

    assert ots.check_ots_anchor(upgraded, RECORD_HASH, header_fetcher=down).state == "error"


def test_garbage_proof_is_a_fail_not_a_crash():
    bad = {"mode": "opentimestamps", "ots": "AAAA"}
    assert ots.check_ots_anchor(bad, RECORD_HASH).state == "fail"
    assert ots.check_ots_anchor({"mode": "opentimestamps", "ots": "***"}, RECORD_HASH).state == "fail"
