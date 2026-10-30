"""
Merkle-batched anchoring: RFC 6962 tree, inclusion proofs, and the end-to-end flow.

The tree is checked against Certificate Transparency reference values, against an
independent naive implementation, and exhaustively for proof validity and tamper
resistance. The flow tests run through the real pipeline with the simulated chain.
"""

from __future__ import annotations

import hashlib
import json
import random

import pytest

from src.blockchain.client import ChainError, MockChainClient, url_commitment
from src.config import Settings
from src.evidence.batch import BatchError, build_batch, check_record_proof, leaf_data, merkle_block
from src.evidence.merkle import (
    EMPTY_ROOT,
    inclusion_proof,
    leaf_hash,
    merkle_root,
    node_hash,
    verify_inclusion,
)
from src.evidence.record import Status, build_payload, load_record, save_record, seal
from src.pipeline import run_anchor_batch, run_verify
from src.ui import Console

CT_LEAVES = [
    b"",
    b"\x00",
    b"\x10",
    b"\x20\x21",
    b"\x30\x31",
    b"\x40\x41\x42\x43",
    bytes(range(0x50, 0x58)),
    bytes(range(0x60, 0x70)),
]


def naive_root(leaves):
    """Independent reference: RFC 6962 MTH written from the definition, no shared helpers."""

    def mth(items):
        if not items:
            return hashlib.sha256(b"").digest()
        if len(items) == 1:
            return hashlib.sha256(b"\x00" + items[0]).digest()
        k = 1
        while k * 2 < len(items):
            k *= 2
        return hashlib.sha256(b"\x01" + mth(items[:k]) + mth(items[k:])).digest()

    return mth(leaves)


class TestTree:
    def test_certificate_transparency_reference_values(self):
        assert EMPTY_ROOT.hex() == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert leaf_hash(b"").hex() == "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d"
        assert merkle_root(CT_LEAVES).hex() == "5dc9da79a70659a9ad559cb701ded9a2ab9d823aad2f4960cfe370eff4604328"

    def test_domain_separation(self):
        a, b = leaf_hash(b"x"), leaf_hash(b"y")
        assert node_hash(a, b) != leaf_hash(a + b)  # an interior node cannot pass as a leaf

    @pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 31, 33, 100])
    def test_matches_an_independent_implementation(self, n):
        rng = random.Random(n)
        leaves = [bytes(rng.randrange(256) for _ in range(rng.randrange(0, 40))) for _ in range(n)]
        assert merkle_root(leaves) == naive_root(leaves)

    def test_every_proof_of_every_size_verifies(self):
        for n in range(1, 66):
            leaves = [hashlib.sha256(bytes([i, n])).digest() for i in range(n)]
            root = merkle_root(leaves)
            for i in range(n):
                proof = inclusion_proof(leaves, i)
                assert verify_inclusion(leaves[i], i, n, proof, root), (n, i)
                assert len(proof) <= (n - 1).bit_length()  # logarithmic

    def test_tampering_is_rejected(self):
        n = 13
        leaves = [bytes([i]) * 8 for i in range(n)]
        root = merkle_root(leaves)
        proof = inclusion_proof(leaves, 6)
        assert verify_inclusion(leaves[6], 6, n, proof, root)
        assert not verify_inclusion(b"forged", 6, n, proof, root)  # wrong leaf
        assert not verify_inclusion(leaves[6], 5, n, proof, root)  # wrong index
        # The size only fixes the *shape* of the path; it is not committed to by the root. A size with
        # the same path shape (14 vs 13 here) verifies, one with a different shape does not. This is
        # inherent to RFC 6962/9162, which is why the on-chain size is informational (see docs).
        assert not verify_inclusion(leaves[6], 6, 7, proof, root)
        assert not verify_inclusion(leaves[6], 6, 20, proof, root)
        assert not verify_inclusion(leaves[6], 6, n, proof[:-1], root)  # truncated
        assert not verify_inclusion(leaves[6], 6, n, proof + [b"\x00" * 32], root)  # extended
        assert not verify_inclusion(leaves[6], 6, n, proof, b"\x00" * 32)  # wrong root
        bad = list(proof)
        bad[0] = bytes(32)
        assert not verify_inclusion(leaves[6], 6, n, bad, root)
        assert not verify_inclusion(leaves[6], -1, n, proof, root)
        assert not verify_inclusion(leaves[6], n, n, proof, root)

    def test_index_out_of_range(self):
        with pytest.raises(IndexError):
            inclusion_proof([b"a"], 1)

    def test_single_leaf_tree_has_an_empty_proof(self):
        assert inclusion_proof([b"only"], 0) == []
        assert verify_inclusion(b"only", 0, 1, [], merkle_root([b"only"]))


H = ["0x" + hashlib.sha256(bytes([i])).hexdigest() for i in range(5)]
U = [url_commitment(f"https://x.com/u/status/{i}") for i in range(5)]


class TestBatchPlan:
    def test_plan_and_proofs(self):
        plan = build_batch(list(zip(H, U, strict=True)))
        assert plan.size == 5 and plan.root.startswith("0x")
        for i in range(5):
            block = merkle_block(plan, i)
            assert check_record_proof(H[i], U[i], block).ok

    def test_leaf_binds_the_url_commitment(self):
        plan = build_batch(list(zip(H, U, strict=True)))
        block = merkle_block(plan, 2)
        assert not check_record_proof(H[2], U[3], block).ok  # right hash, different URL
        assert not check_record_proof(H[3], U[2], block).ok  # right URL, different hash

    def test_rejections(self):
        with pytest.raises(BatchError):
            build_batch([])
        with pytest.raises(BatchError):
            build_batch([(H[0], U[0]), (H[0], U[0])])
        with pytest.raises(BatchError):
            leaf_data("0x12", U[0])
        with pytest.raises(BatchError):
            leaf_data("zz" * 32, U[0])

    @pytest.mark.parametrize(
        "block",
        [
            None,
            "x",
            {},
            {"root": "0x00", "index": 0, "size": 1, "proof": []},
            {"root": "0x" + "00" * 32, "index": "0", "size": 1, "proof": []},
            {"root": "0x" + "00" * 32, "index": 0, "size": 0, "proof": []},
            {"root": "0x" + "00" * 32, "index": 0, "size": 1, "proof": ["nothex"]},
            {"root": "0x" + "00" * 32, "index": 0, "size": 1, "proof": ["0x" + "00" * 32] * 65},
        ],
    )
    def test_malformed_blocks_fail_closed(self, block):
        assert not check_record_proof(H[0], U[0], block).ok


# ----------------------------------------------------------------- end to end


def make_record(settings, i):
    url = f"https://x.com/user/status/{i}"
    payload = build_payload(
        source_image={"filename": f"{i}.png", "sha256": f"{i:064x}"},
        face={"engine": "x"},
        search={"provider": "x"},
        match={"matched_url": url, "decision_rule": "confirmed_face_match"},
        created_at="2026-01-01T00:00:00Z",
    )
    record = seal(payload)
    record["anchor"] = {"mode": "merkle_batch", "status": "pending"}
    return save_record(record, settings.output_dir / f"r{i}.json")


@pytest.fixture
def pending(settings):
    return [make_record(settings, i) for i in range(5)]


def verify(settings, path):
    report: dict = {}
    code = run_verify(settings, path, dry_run=True, console=Console(force_ascii=True), report=report)
    return code, report


class TestEndToEnd:
    def test_pending_records_are_not_anchored(self, settings, pending):
        code, report = verify(settings, pending[0])
        assert code == Status.NOT_ANCHORED.exit_code
        assert report["checks"]["merkle_inclusion"]["status"] == "fail"

    def test_one_transaction_anchors_every_record(self, settings, pending):
        assert run_anchor_batch(settings, pending, dry_run=True, console=Console(force_ascii=True)) == 0
        state = json.loads((settings.root / "localchain.json").read_text(encoding="utf-8"))
        assert len(state["batches"]) == 1 and state["records"] == {} and state["head"] == 1  # ONE block
        for path in pending:
            code, report = verify(settings, path)
            assert code == 0, report
            assert report["verdict"] == "verified" and report["anchor_mode"] == "merkle_batch"
            assert report["checks"]["merkle_inclusion"]["status"] == "pass"
            assert report["checks"]["chain_anchor"]["status"] == "pass"
            assert report["checks"]["url_commitment"]["status"] == "pass"
            assert report["chain"]["batch_size"] == 5

    def test_each_record_has_its_own_proof(self, settings, pending):
        run_anchor_batch(settings, pending, dry_run=True, console=Console(force_ascii=True))
        blocks = [load_record(p)["anchor"]["merkle"] for p in pending]
        assert len({b["root"] for b in blocks}) == 1
        assert [b["index"] for b in blocks] == [0, 1, 2, 3, 4]
        assert all(b["size"] == 5 for b in blocks)

    def test_edited_record_fails_integrity(self, settings, pending):
        run_anchor_batch(settings, pending, dry_run=True, console=Console(force_ascii=True))
        record = load_record(pending[1])
        record["payload"]["match"]["matched_url"] = "https://x.com/attacker/1"
        save_record(record, pending[1])
        assert verify(settings, pending[1])[0] == Status.LOCAL_HASH_MISMATCH.exit_code

    def test_resealed_record_cannot_reuse_a_valid_proof(self, settings, pending):
        run_anchor_batch(settings, pending, dry_run=True, console=Console(force_ascii=True))
        record = load_record(pending[1])
        anchor = record["anchor"]
        record["payload"]["match"]["matched_url"] = "https://x.com/attacker/1"
        forged = seal(record["payload"])
        forged["anchor"] = anchor
        path = save_record(forged, settings.output_dir / "forged.json")
        code, report = verify(settings, path)
        assert code == Status.ANCHOR_MISMATCH.exit_code
        assert report["checks"]["local_integrity"]["status"] == "pass"
        assert report["checks"]["merkle_inclusion"]["status"] == "fail"

    def test_swapped_proof_between_records_fails(self, settings, pending):
        run_anchor_batch(settings, pending, dry_run=True, console=Console(force_ascii=True))
        a, b = load_record(pending[0]), load_record(pending[1])
        a["anchor"]["merkle"] = b["anchor"]["merkle"]
        save_record(a, pending[0])
        assert verify(settings, pending[0])[0] == Status.ANCHOR_MISMATCH.exit_code

    def test_unregistered_root_is_not_anchored(self, settings, pending):
        run_anchor_batch(settings, pending, dry_run=True, console=Console(force_ascii=True))
        (settings.root / "localchain.json").unlink()  # the chain never saw this batch
        code, report = verify(settings, pending[0])
        assert code == Status.NOT_ANCHORED.exit_code
        assert report["checks"]["merkle_inclusion"]["status"] == "pass"  # proof is fine...
        assert report["checks"]["chain_anchor"]["status"] == "fail"  # ...but nothing is registered

    def test_lookup_failure_is_inconclusive(self, settings, pending, monkeypatch):
        import src.pipeline as pipeline
        from src.blockchain.client import ChainError

        run_anchor_batch(settings, pending, dry_run=True, console=Console(force_ascii=True))

        class Broken(MockChainClient):
            def lookup_batch(self, root):
                raise ChainError("batch lookup failed: timeout")

        monkeypatch.setattr(pipeline, "build_chain_client", lambda *a, **k: Broken(settings))
        code, report = verify(settings, pending[0])
        assert code == Status.INCONCLUSIVE.exit_code
        assert report["checks"]["merkle_inclusion"]["status"] == "pass"

    def test_batch_guards(self, settings, pending):
        ui = Console(force_ascii=True)
        assert run_anchor_batch(settings, pending, dry_run=True, console=ui) == 0
        # already anchored: refused, nothing re-registered
        assert run_anchor_batch(settings, pending[:1], dry_run=True, console=ui) == 1
        # a record that fails local integrity is never batched
        record = load_record(make_record(settings, 99))
        record["payload"]["match"]["matched_url"] = "https://x.com/edited"
        bad = save_record(record, settings.output_dir / "bad.json")
        assert run_anchor_batch(settings, [bad], dry_run=True, console=ui) == 1

    def test_mock_batches_are_first_write_wins(self, settings):
        client = MockChainClient(settings)
        root = "0x" + "ab" * 32
        client.register_batch(root, 3)
        with pytest.raises(Exception, match="already anchored"):
            client.register_batch(root, 3)
        assert client.lookup_batch(root).size == 3
        assert client.lookup_batch("0x" + "cd" * 32).exists is False
        with pytest.raises(ChainError):
            client.register_batch("0x" + "ee" * 32, 0)

    def test_register_in_batch_mode_seals_without_anchoring(self, settings, scene):
        from src.pipeline import run_register

        settings.fixture_path = str(scene["fixture"])
        code = run_register(
            settings,
            scene["query"],
            provider_name="local_fixture",
            engine_name="stub",
            dry_run=True,
            allow_offline_stub=True,
            anchor_mode="batch",
            console=Console(force_ascii=True),
        )
        assert code == 0
        record = load_record(settings.output_dir / "verification.json")
        assert record["anchor"] == {"mode": "merkle_batch", "status": "pending"}
        assert not (settings.root / "localchain.json").exists()  # nothing was written to any chain
        assert (
            run_anchor_batch(
                settings, [settings.output_dir / "verification.json"], dry_run=True, console=Console(force_ascii=True)
            )
            == 0
        )
        assert verify(settings, settings.output_dir / "verification.json")[0] == 0


def test_settings_fixture_is_isolated(tmp_path):
    s = Settings()
    s.root = tmp_path
    assert MockChainClient(s).path.parent == tmp_path
