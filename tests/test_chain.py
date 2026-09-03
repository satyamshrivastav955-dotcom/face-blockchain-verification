"""
Chain layer: the simulated client's semantics, and the contract's invariants.

The real deployment cannot be exercised without a funded testnet key, so the
mock client is written to reproduce the semantics that actually matter -
append-only, first-write-wins, submitter recorded - and those are what is
tested. The contract itself is checked at source level for the properties that
would silently destroy tamper-evidence if someone "simplified" it later.
"""

from __future__ import annotations

import json

import pytest

from src.chain import (
    CONTRACT_SOURCE,
    AnchorResult,
    ChainError,
    ChainRecord,
    MockChainClient,
    build_chain_client,
)
from src.config import Settings

HASH_A = "0x" + "a1" * 32
HASH_B = "0x" + "b2" * 32
URL_A = "https://x.com/realuser/status/1234567890"


@pytest.fixture
def client(tmp_path):
    settings = Settings()
    settings.root = tmp_path
    return MockChainClient(settings)


class TestRegister:
    def test_returns_an_anchor(self, client):
        anchor = client.register(HASH_A, URL_A)
        assert isinstance(anchor, AnchorResult)
        assert anchor.data_hash == HASH_A
        assert anchor.tx_hash.startswith("0x")
        assert anchor.block_number >= 1
        assert anchor.block_timestamp > 0
        assert anchor.simulated is True

    def test_simulated_flag_is_in_the_json(self, client):
        """A dry-run record must never be mistakable for a real one."""
        assert client.register(HASH_A, URL_A).to_json()["simulated"] is True

    def test_anchor_json_is_canonicalizable(self, client):
        from src.canonical import canonicalize

        canonicalize(client.register(HASH_A, URL_A).to_json())

    def test_first_write_wins(self, client):
        client.register(HASH_A, URL_A)
        with pytest.raises(ChainError) as excinfo:
            client.register(HASH_A, "https://x.com/attacker/status/999")
        assert "already anchored" in str(excinfo.value)

    def test_the_original_survives_a_second_attempt(self, client):
        client.register(HASH_A, URL_A)
        with pytest.raises(ChainError):
            client.register(HASH_A, "https://evil.example/")
        assert client.lookup(HASH_A).extra["source_url"] == URL_A

    def test_distinct_hashes_both_register(self, client):
        first = client.register(HASH_A, URL_A)
        second = client.register(HASH_B, "https://instagram.com/p/xyz/")
        assert second.block_number > first.block_number

    def test_case_insensitive_hash_keys(self, client):
        client.register(HASH_A.lower(), URL_A)
        assert client.lookup(HASH_A.upper()).exists


class TestLookup:
    def test_unknown_hash_does_not_exist(self, client):
        record = client.lookup(HASH_B)
        assert isinstance(record, ChainRecord)
        assert record.exists is False
        assert record.timestamp == 0

    def test_known_hash_returns_its_metadata(self, client):
        client.register(HASH_A, URL_A)
        record = client.lookup(HASH_A)
        assert record.exists
        assert record.submitter.startswith("0x")
        assert record.timestamp > 0
        assert record.url_hash

    def test_url_commitment_matches(self, client):
        client.register(HASH_A, URL_A)
        assert client.matches_url(HASH_A, URL_A)
        assert not client.matches_url(HASH_A, URL_A + "?utm=1")
        assert not client.matches_url(HASH_B, URL_A)


class TestPersistence:
    def test_state_survives_a_new_client(self, tmp_path):
        settings = Settings()
        settings.root = tmp_path
        MockChainClient(settings).register(HASH_A, URL_A)
        assert MockChainClient(settings).lookup(HASH_A).exists

    def test_state_lives_under_the_configured_root(self, tmp_path):
        settings = Settings()
        settings.root = tmp_path
        client = MockChainClient(settings)
        client.register(HASH_A, URL_A)
        assert (tmp_path / "localchain.json").exists()

    def test_corrupt_state_file_does_not_crash(self, tmp_path):
        settings = Settings()
        settings.root = tmp_path
        (tmp_path / "localchain.json").write_text("{not json", encoding="utf-8")
        client = MockChainClient(settings)
        assert client.register(HASH_A, URL_A).block_number == 1

    def test_describe(self, client):
        client.register(HASH_A, URL_A)
        described = client.describe()
        assert described["simulated"] is True
        assert described["records"] == 1


class TestBuildChainClient:
    def test_dry_run_gives_the_mock(self, tmp_path):
        settings = Settings()
        settings.root = tmp_path
        assert isinstance(build_chain_client(settings, dry_run=True), MockChainClient)

    def test_real_client_without_an_rpc_fails_loudly(self, tmp_path):
        settings = Settings()
        settings.root = tmp_path
        settings.rpc_url = ""
        with pytest.raises(ChainError):
            build_chain_client(settings, dry_run=False, require_signer=False)


class TestContractInvariants:
    """Source-level guards on the properties that make the registry trustworthy.

    These are intentionally crude string assertions. They exist because each of
    these lines can be deleted or "simplified" by someone who does not realise
    that doing so quietly removes the tamper-evidence the project claims.
    """

    @pytest.fixture(scope="class")
    def source(self):
        return CONTRACT_SOURCE.read_text(encoding="utf-8")

    def test_first_write_wins_guard_present(self, source):
        assert "existing.timestamp != 0" in source
        assert "AlreadyRegistered" in source

    def test_no_privileged_functions(self, source):
        for forbidden in ("onlyOwner", "selfdestruct", "delegatecall", "Ownable"):
            assert forbidden not in source, f"{forbidden} would break append-only"

    def test_no_deletion(self, source):
        assert "delete _records" not in source

    def test_records_mapping_is_private(self, source):
        # A public getter returns a zero-filled struct for a missing key, which
        # callers routinely misread as a valid record.
        assert "mapping(bytes32 => Record) private _records" in source

    def test_submitter_is_msg_sender(self, source):
        assert "submitter: msg.sender" in source

    def test_event_carries_the_full_url(self, source):
        assert "string sourceUrl" in source

    def test_no_biometric_field(self, source):
        """The struct must hold only the four intended fields, none biometric."""
        struct = source.split("struct Record {")[1].split("}")[0]
        assert struct.count(";") == 4
        assert "bytes32 urlHash" in struct
        for forbidden in ("embedding", "biometric", "descriptor", "template"):
            assert forbidden not in struct.lower()

    def test_licence_and_pragma(self, source):
        assert source.startswith("// SPDX-License-Identifier:")
        assert "pragma solidity ^0.8" in source


class TestArtifactHandling:
    def test_missing_artifact_is_explained(self, monkeypatch, tmp_path):
        import src.chain as chain

        monkeypatch.setattr(chain, "ARTIFACT_PATH", tmp_path / "nope.json")
        with pytest.raises(ChainError) as excinfo:
            chain.load_artifact()
        assert "deploy" in str(excinfo.value)

    def test_cached_artifact_is_reused(self, monkeypatch, tmp_path):
        import src.chain as chain

        artifact = {"contractName": "VerificationRegistry", "abi": [], "bytecode": "60"}
        path = tmp_path / "VerificationRegistry.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        monkeypatch.setattr(chain, "ARTIFACT_PATH", path)
        # Must not need solc: a cached artifact is what makes an offline deploy
        # (and this test) possible.
        assert chain.compile_contract()["bytecode"] == "60"
