"""
Behavioural tests of the registry contract and the real ``EvmChainClient`` on an
in-process EVM (eth-tester / py-evm). No network, no real wallet, no gas.

These tests compile ``contracts/VerificationRegistry.sol`` with a locally
installed solc (py-solc-x) and execute it, so they check the contract's actual
invariants rather than source-code strings. They are skipped - with the reason
shown - when ``eth-tester[py-evm]`` or solc 0.8.24 is not installed
(``pip install -r requirements-dev.txt``).

Keys used here are eth-tester's well-known throwaway test keys; they control
nothing outside this process.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("eth_tester", reason="eth-tester[py-evm] not installed")
pytest.importorskip("web3")
solcx = pytest.importorskip("solcx", reason="py-solc-x not installed")

from eth_tester import EthereumTester, PyEVMBackend  # noqa: E402
from web3 import EthereumTesterProvider, Web3  # noqa: E402
from eth_tester.exceptions import TransactionFailed  # noqa: E402

from src.blockchain import client as client_mod  # noqa: E402
from src.blockchain.client import (  # noqa: E402
    REGISTRY_VERSION,
    ChainError,
    EvmChainClient,
    IncompatibleContractError,
    url_commitment,
)
from src.config import Settings  # noqa: E402

pytestmark = pytest.mark.skipif(
    client_mod.SOLC_VERSION not in [str(v) for v in solcx.get_installed_solc_versions()],
    reason=f"solc {client_mod.SOLC_VERSION} is not installed locally",
)

HASH_A = "0x" + "a1" * 32
HASH_B = "0x" + "b2" * 32
URL_A = "https://x.com/realuser/status/1234567890"
URL_B = "https://instagram.com/p/other/"


@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    """Compile the current source fresh (never trusts a cached build)."""
    path = tmp_path_factory.mktemp("build") / "VerificationRegistry.json"
    mp = pytest.MonkeyPatch()
    mp.setattr(client_mod, "ARTIFACT_PATH", path)
    try:
        return client_mod.compile_contract(force=True)
    finally:
        mp.undo()


@pytest.fixture
def chain(monkeypatch, artifact, tmp_path):
    tester = EthereumTester(PyEVMBackend())
    provider = EthereumTesterProvider(tester)
    monkeypatch.setattr(Web3, "HTTPProvider", lambda *a, **k: provider)
    art_path = tmp_path / "VerificationRegistry.json"
    art_path.write_text(json.dumps(artifact), encoding="utf-8")
    monkeypatch.setattr(client_mod, "ARTIFACT_PATH", art_path)

    settings = Settings()
    settings.root = tmp_path
    settings.chain_name = "eth-tester"
    settings.chain_id = int(Web3(provider).eth.chain_id)
    settings.rpc_url = "http://127.0.0.1:0"  # never dialled: provider is patched
    settings.private_key = tester.backend.account_keys[0].to_hex()
    return tester, settings


@pytest.fixture
def deployed(chain):
    tester, settings = chain
    deployer = EvmChainClient(settings)
    address, _tx = deployer.deploy()
    settings.contract_address = address
    return tester, settings, EvmChainClient(settings)


class TestRegistryBehaviour:
    def test_register_then_lookup(self, deployed):
        tester, settings, client = deployed
        anchor = client.register(HASH_A, URL_A)
        assert anchor.tx_hash.startswith("0x") and anchor.block_number >= 1
        assert anchor.simulated is False
        assert anchor.url_commitment == url_commitment(URL_A)

        record = client.lookup(HASH_A)
        assert record.exists
        assert record.submitter == client.account.address
        assert record.block_number == anchor.block_number
        assert record.timestamp == anchor.block_timestamp
        assert record.url_hash == url_commitment(URL_A)

    def test_unknown_hash_does_not_exist(self, deployed):
        _, _, client = deployed
        record = client.lookup(HASH_B)
        assert record.exists is False
        assert record.timestamp == 0 and record.submitter.endswith("0" * 40)
        assert client.contract.functions.isRegistered(bytes.fromhex(HASH_B[2:])).call() is False

    def test_first_write_wins(self, deployed):
        _, _, client = deployed
        client.register(HASH_A, URL_A)
        with pytest.raises(ChainError) as excinfo:
            client.register(HASH_A, URL_B)
        assert "already anchored" in str(excinfo.value)
        # The original commitment is untouched.
        assert client.lookup(HASH_A).url_hash == url_commitment(URL_A)
        assert client.contract.functions.totalRecords().call() == 1

    def test_zero_hash_is_rejected(self, deployed):
        _, _, client = deployed
        with pytest.raises(ChainError):
            client.register("0x" + "00" * 32, URL_A)

    def test_zero_url_commitment_is_rejected_by_the_contract(self, deployed):
        tester, settings, client = deployed
        with pytest.raises(TransactionFailed) as excinfo:
            client.contract.functions.register(bytes.fromhex(HASH_A[2:]), b"\x00" * 32).call(
                {"from": client.account.address}
            )
        from eth_utils.crypto import keccak

        # eth-tester reports the revert data (the custom-error selector) as the message
        assert str(excinfo.value).endswith(str(keccak(b"ZeroHash()")[:4]))

    def test_url_commitment_verification(self, deployed):
        _, _, client = deployed
        client.register(HASH_A, URL_A)
        assert client.matches_url(HASH_A, URL_A) is True
        assert client.matches_url(HASH_A, URL_A + "?utm=1") is False  # exact bytes
        assert client.matches_url(HASH_A, URL_B) is False
        assert client.matches_url(HASH_B, URL_A) is False  # unknown record

    def test_no_privileged_functions_in_the_abi(self, artifact):
        names = {item.get("name") for item in artifact["abi"] if item["type"] == "function"}
        assert names == {
            "register",
            "verify",
            "isRegistered",
            "matchesUrlHash",
            "totalRecords",
            "registryVersion",
            "registerBatch",
            "verifyBatch",
            "totalBatches",
        }

    def test_registry_version(self, deployed):
        _, _, client = deployed
        assert client.check_compatibility() == REGISTRY_VERSION == 3


class TestNoPlaintextUrlOnChain:
    """The privacy fix: the URL must not appear in calldata, logs or storage."""

    def test_calldata_and_events_do_not_contain_the_url(self, deployed):
        tester, settings, client = deployed
        anchor = client.register(HASH_A, URL_A)
        w3 = client.w3
        tx = w3.eth.get_transaction(anchor.tx_hash)
        receipt = w3.eth.get_transaction_receipt(anchor.tx_hash)

        needle = URL_A.encode()
        calldata = bytes.fromhex(tx["input"].hex().removeprefix("0x"))
        assert needle not in calldata
        assert b"x.com" not in calldata
        # selector + two bytes32 arguments, nothing else
        assert len(calldata) == 4 + 32 + 32
        assert len(receipt["logs"]) == 1
        log = receipt["logs"][0]
        blob = b"".join(bytes(t) for t in log["topics"]) + bytes(log["data"])
        assert needle not in blob and b"x.com" not in blob
        # the commitment is there, as an indexed topic
        assert bytes.fromhex(url_commitment(URL_A)[2:]) in [bytes(t) for t in log["topics"]]

    def test_storage_holds_no_url_either(self, deployed):
        _, _, client = deployed
        client.register(HASH_A, URL_A)
        for slot in range(0, 8):
            word = bytes(client.w3.eth.get_storage_at(client.contract.address, slot))
            assert b"x.com" not in word


class TestClientErrorHandling:
    def test_chain_id_mismatch(self, chain):
        _, settings = chain
        settings.chain_id += 1
        with pytest.raises(ChainError) as excinfo:
            EvmChainClient(settings, require_signer=False)
        assert "chain id mismatch" in str(excinfo.value)

    def test_read_only_client_needs_no_private_key(self, deployed):
        _, settings, writer = deployed
        writer.register(HASH_A, URL_A)
        settings.private_key = ""
        reader = EvmChainClient(settings, require_signer=False)
        assert reader.account is None
        assert reader.lookup(HASH_A).exists
        assert reader.matches_url(HASH_A, URL_A)
        with pytest.raises(ChainError):
            reader.register(HASH_B, URL_A)

    def test_invalid_contract_address(self, chain):
        _, settings = chain
        settings.contract_address = "0x1234"
        with pytest.raises(ChainError):
            EvmChainClient(settings, require_signer=False)

    def test_address_with_no_code_is_incompatible(self, chain):
        _, settings = chain
        settings.contract_address = "0x" + "12" * 20
        with pytest.raises(IncompatibleContractError) as excinfo:
            EvmChainClient(settings, require_signer=False)
        assert "no contract code" in str(excinfo.value)

    def test_old_v1_registry_is_detected_not_silently_accepted(self, chain):
        """A v1 deployment (plaintext-URL interface) has no registryVersion()."""
        tester, settings = chain
        v1_source = """
        // SPDX-License-Identifier: MIT
        pragma solidity ^0.8.20;
        contract VerificationRegistry {
            event Registered(bytes32 indexed dataHash, string sourceUrl);
            function register(bytes32 dataHash, string calldata sourceUrl) external {
                emit Registered(dataHash, sourceUrl);
            }
            function verify(bytes32) external pure returns (bool, address, uint48, uint48, bytes32) {
                return (false, address(0), 0, 0, bytes32(0));
            }
        }
        """
        compiled = solcx.compile_source(v1_source, output_values=["abi", "bin"], solc_version=client_mod.SOLC_VERSION)
        _, iface = next(iter(compiled.items()))
        w3 = Web3(EthereumTesterProvider(tester))
        # Reuse the same tester instance: deploy from its first funded account.
        tx = (
            w3.eth.contract(abi=iface["abi"], bytecode=iface["bin"])
            .constructor()
            .transact({"from": tester.get_accounts()[1]})
        )
        address = w3.eth.get_transaction_receipt(tx)["contractAddress"]
        settings.contract_address = address
        with pytest.raises(IncompatibleContractError) as excinfo:
            EvmChainClient(settings, require_signer=False)
        assert "v1" in str(excinfo.value) and "registryVersion" in str(excinfo.value)

    def test_lookup_failure_is_a_chain_error_not_a_negative(self, deployed, monkeypatch):
        _, _, client = deployed

        def boom(*a, **k):
            raise ConnectionError("rpc went away")

        monkeypatch.setattr(client.contract.functions, "verify", boom)
        with pytest.raises(ChainError) as excinfo:
            client.lookup(HASH_A)
        assert "lookup failed" in str(excinfo.value)

    def test_url_check_failure_is_a_chain_error_not_false(self, deployed, monkeypatch):
        _, _, client = deployed
        client.register(HASH_A, URL_A)

        def boom(*a, **k):
            raise TimeoutError("slow rpc")

        monkeypatch.setattr(client.contract.functions, "matchesUrlHash", boom)
        with pytest.raises(ChainError) as excinfo:
            client.matches_url(HASH_A, URL_A)
        assert "could not be completed" in str(excinfo.value) or "failed" in str(excinfo.value)

    def test_reverted_receipt_is_an_error(self, deployed, monkeypatch):
        _, _, client = deployed
        real = client.w3.eth.wait_for_transaction_receipt

        def failing(tx_hash, timeout=0, **k):
            receipt = dict(real(tx_hash, timeout=timeout))
            receipt["status"] = 0
            return receipt

        monkeypatch.setattr(client.w3.eth, "wait_for_transaction_receipt", failing)
        with pytest.raises(ChainError) as excinfo:
            client.register(HASH_A, URL_A)
        assert "reverted" in str(excinfo.value)

    def test_receipt_timeout_is_an_error(self, deployed, monkeypatch):
        from web3.exceptions import TimeExhausted

        _, _, client = deployed

        def timeout(*a, **k):
            raise TimeExhausted("no receipt")

        monkeypatch.setattr(client.w3.eth, "wait_for_transaction_receipt", timeout)
        with pytest.raises(ChainError) as excinfo:
            client.register(HASH_A, URL_A)
        assert "could not be confirmed" in str(excinfo.value)


class TestVerifyThroughTheRealClient:
    """run_verify against the EVM client: the integration the mock cannot prove."""

    def _record(self, client, url=URL_A):
        from src.evidence.record import attach_anchor, build_payload, seal

        payload = build_payload(
            source_image={"filename": "q.png", "sha256": "0" * 64},
            face={"engine": "x"},
            search={"provider": "x"},
            match={"matched_url": url, "decision_rule": "confirmed_face_match"},
            created_at="2026-01-01T00:00:00Z",
        )
        record = seal(payload)
        anchor = client.register(record["integrity"]["verification_hash"], url)
        attach_anchor(record, anchor.to_json())
        return record

    def test_verified_end_to_end(self, deployed, tmp_path, monkeypatch):
        from src.evidence.record import save_record
        from src.pipeline import run_verify
        from src.ui import Console

        _, settings, client = deployed
        path = save_record(self._record(client), tmp_path / "r.json")
        settings.private_key = ""
        report: dict = {}
        code = run_verify(settings, path, console=Console(force_ascii=True), report=report)
        assert code == 0
        assert report["verdict"] == "verified" and report["simulated"] is False
        assert report["checks"]["url_commitment"]["status"] == "pass"

    def test_old_contract_gives_inconclusive_not_verified(self, chain, tmp_path):
        from src.evidence.record import attach_anchor, save_record, seal
        from src.pipeline import run_verify
        from src.ui import Console

        _, settings = chain
        settings.contract_address = "0x" + "12" * 20  # no code at this address
        record = seal({"schema": "faceverify/v2", "match": {"matched_url": URL_A}})
        attach_anchor(record, {})
        path = save_record(record, tmp_path / "r.json")
        report: dict = {}
        code = run_verify(settings, path, console=Console(force_ascii=True), report=report)
        assert code == 6
        assert report["verdict"] == "inconclusive"
        assert report["checks"]["chain_anchor"]["status"] == "error"


ROOT_A = "0x" + "c1" * 32
ROOT_B = "0x" + "d2" * 32


class TestMerkleBatches:
    """Registry v3: one transaction anchors a whole batch."""

    def test_register_and_lookup(self, deployed):
        _, _, client = deployed
        anchor = client.register_batch(ROOT_A, 40)
        assert anchor.tx_hash.startswith("0x") and anchor.registry_version == 3
        batch = client.lookup_batch(ROOT_A)
        assert batch.exists and batch.size == 40
        assert batch.submitter == client.account.address
        assert batch.block_number == anchor.block_number and batch.timestamp == anchor.block_timestamp
        assert client.contract.functions.totalBatches().call() == 1

    def test_unknown_root(self, deployed):
        _, _, client = deployed
        assert client.lookup_batch(ROOT_B).exists is False

    def test_first_write_wins_and_nothing_changes(self, deployed):
        _, _, client = deployed
        client.register_batch(ROOT_A, 5)
        with pytest.raises(ChainError) as excinfo:
            client.register_batch(ROOT_A, 999)
        assert "already anchored" in str(excinfo.value)
        assert client.lookup_batch(ROOT_A).size == 5  # untouched

    def test_zero_root_and_empty_batch_are_rejected(self, deployed):
        _, _, client = deployed
        with pytest.raises(ChainError):
            client.register_batch("0x" + "00" * 32, 1)
        with pytest.raises(ChainError):
            client.register_batch(ROOT_B, 0)
        with pytest.raises(ChainError):
            client.register_batch(ROOT_B, 2**32)

    def test_event_carries_only_the_root_size_and_time(self, deployed):
        _, _, client = deployed
        anchor = client.register_batch(ROOT_A, 7)
        receipt = client.w3.eth.get_transaction_receipt(anchor.tx_hash)
        assert len(receipt["logs"]) == 1
        calldata = bytes.fromhex(client.w3.eth.get_transaction(anchor.tx_hash)["input"].hex().removeprefix("0x"))
        assert len(calldata) == 4 + 32 + 32  # selector + root + size, nothing else

    def test_single_and_batch_records_coexist(self, deployed):
        _, _, client = deployed
        client.register(HASH_A, URL_A)
        client.register_batch(ROOT_A, 3)
        assert client.lookup(HASH_A).exists and client.lookup_batch(ROOT_A).exists
        assert client.lookup_batch(HASH_A).exists is False  # namespaces do not collide

    def test_gas_is_amortised_across_the_batch(self, deployed):
        """The reason batching exists: one transaction's gas, however many records it covers."""
        _, _, client = deployed
        # Warm both counters first: the very first write to a zero storage slot costs ~17k more.
        client.register(HASH_B, URL_B)
        client.register_batch("0x" + "a0" * 32, 1)
        single = client.register(HASH_A, URL_A).gas_used
        small = client.register_batch(ROOT_A, 1).gas_used
        large = client.register_batch(ROOT_B, 1000).gas_used
        assert abs(large - small) < 2_000  # batch size does not change the cost
        assert large / 1000 < single / 50  # more than 50x cheaper per record at 1000 records
        assert large < 2 * single  # one batch costs about one single registration
        print(f"GAS single={single} batch(1)={small} batch(1000)={large} per-record@1000={large / 1000:.1f}")

    def test_a_v2_registry_is_accepted_but_cannot_batch(self, chain):
        from src.blockchain.client import IncompatibleContractError

        tester, settings = chain
        v2_source = """
        // SPDX-License-Identifier: MIT
        pragma solidity ^0.8.20;
        contract VerificationRegistry {
            function registryVersion() external pure returns (uint8) { return 2; }
        }
        """
        compiled = solcx.compile_source(v2_source, output_values=["abi", "bin"], solc_version=client_mod.SOLC_VERSION)
        _, iface = next(iter(compiled.items()))
        w3 = Web3(EthereumTesterProvider(tester))
        tx = (
            w3.eth.contract(abi=iface["abi"], bytecode=iface["bin"])
            .constructor()
            .transact({"from": tester.get_accounts()[1]})
        )
        settings.contract_address = w3.eth.get_transaction_receipt(tx)["contractAddress"]
        client = EvmChainClient(settings)  # v2 is still compatible for single records
        assert client.registry_version == 2
        with pytest.raises(IncompatibleContractError) as excinfo:
            client.register_batch(ROOT_A, 1)
        assert "needs v3" in str(excinfo.value)

    def test_end_to_end_verify_through_the_real_client(self, deployed, tmp_path):
        from src.blockchain.client import url_commitment
        from src.evidence.batch import build_batch, merkle_block
        from src.evidence.record import attach_anchor, build_payload, save_record, seal
        from src.pipeline import run_verify
        from src.ui import Console

        _, settings, client = deployed
        urls = [f"https://x.com/u/status/{i}" for i in range(6)]
        records = []
        for i, url in enumerate(urls):
            payload = build_payload(
                source_image={"filename": "q.png", "sha256": f"{i:064x}"},
                face={"engine": "x"},
                search={"provider": "x"},
                match={"matched_url": url, "decision_rule": "confirmed_face_match"},
                created_at="2026-01-01T00:00:00Z",
            )
            records.append(seal(payload))
        plan = build_batch(
            [(r["integrity"]["verification_hash"], url_commitment(u)) for r, u in zip(records, urls, strict=True)]
        )
        anchor = client.register_batch(plan.root, plan.size)
        settings.private_key = ""
        for i, record in enumerate(records):
            block = anchor.to_json()
            block.pop("url_commitment", None)
            block.update({"mode": "merkle_batch", "merkle": merkle_block(plan, i)})
            attach_anchor(record, block)
            path = save_record(record, tmp_path / f"r{i}.json")
            report: dict = {}
            code = run_verify(settings, path, console=Console(force_ascii=True), report=report)
            assert code == 0 and report["verdict"] == "verified", report
            assert report["chain"]["batch_size"] == 6 and report["simulated"] is False
