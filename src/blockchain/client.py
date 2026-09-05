"""
Blockchain layer: compile, deploy, anchor, and look up verification hashes.

CHAIN CHOICE (Base Sepolia)
===========================
Base Sepolia is an OP-Stack Ethereum L2 testnet. It was chosen over Polygon
Amoy and Ethereum Sepolia for three practical reasons: its faucets are the most
reliable of the three (a dry faucet on the evening of a deadline is a real
project risk), block times are ~2s so a demo does not stall waiting for
confirmation, and BaseScan renders the event log legibly, which matters when the
transaction has to be shown on camera.

Nothing here is Base-specific. It is a standard EVM chain reached over JSON-RPC,
so pointing ``RPC_URL``, ``CHAIN_ID`` and ``EXPLORER_BASE`` at Amoy, Sepolia or a
local node is a configuration change, not a code change.

WEB3 VERSION COMPATIBILITY
==========================
web3.py v7 renamed several things that v6 code depends on - most awkwardly
``SignedTransaction.rawTransaction`` became ``raw_transaction``, and the PoA
middleware moved and was renamed. Both are handled below so the project works
on either major version rather than pinning users to one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..evidence.hashing import sha256_bytes
from ..config import PROJECT_ROOT, Settings

__all__ = [
    "ChainError",
    "AnchorResult",
    "ChainRecord",
    "ChainClient",
    "EvmChainClient",
    "MockChainClient",
    "build_chain_client",
    "compile_contract",
    "load_artifact",
]

CONTRACT_NAME = "VerificationRegistry"
CONTRACT_SOURCE = PROJECT_ROOT / "contracts" / f"{CONTRACT_NAME}.sol"
BUILD_DIR = PROJECT_ROOT / "contracts" / "build"
ARTIFACT_PATH = BUILD_DIR / f"{CONTRACT_NAME}.json"
SOLC_VERSION = "0.8.24"


class ChainError(RuntimeError):
    """A blockchain operation failed."""


@dataclass
class AnchorResult:
    """Where and when a hash was anchored."""

    data_hash: str
    tx_hash: str
    block_number: int
    block_timestamp: int
    contract_address: str
    submitter: str
    chain_id: int
    network: str
    gas_used: int = 0
    explorer_url: str = ""
    simulated: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "chain_id": int(self.chain_id),
            "contract_address": self.contract_address,
            "tx_hash": self.tx_hash,
            "block_number": int(self.block_number),
            "block_timestamp": int(self.block_timestamp),
            "submitter": self.submitter,
            "gas_used": int(self.gas_used),
            "explorer_url": self.explorer_url,
            "simulated": bool(self.simulated),
        }


@dataclass
class ChainRecord:
    """What the chain says about a hash."""

    exists: bool
    submitter: str = ""
    timestamp: int = 0
    block_number: int = 0
    url_hash: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class ChainClient(Protocol):
    network: str
    chain_id: int
    simulated: bool

    def register(self, data_hash: str, source_url: str) -> AnchorResult: ...
    def lookup(self, data_hash: str) -> ChainRecord: ...
    def describe(self) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def _get_artifact_path():
    import sys
    chain_mod = sys.modules.get("src.chain")
    if chain_mod is not None and hasattr(chain_mod, "ARTIFACT_PATH"):
        return chain_mod.ARTIFACT_PATH
    return ARTIFACT_PATH


def compile_contract(*, force: bool = False) -> dict[str, Any]:
    """Compile the Solidity source and cache the ABI + bytecode.

    The artifact is cached because ``solc`` has to be downloaded on first use,
    which needs network access - so a cached artifact means deploying later
    (or on a locked-down machine) does not require the compiler at all.
    """
    art_path = _get_artifact_path()
    if art_path.exists() and not force:
        return load_artifact()

    if not CONTRACT_SOURCE.exists():
        raise ChainError(f"contract source missing: {CONTRACT_SOURCE}")

    try:
        import solcx
    except ImportError as exc:
        raise ChainError(
            "py-solc-x is not installed (pip install py-solc-x), and no prebuilt "
            f"artifact was found at {ARTIFACT_PATH}"
        ) from exc

    try:
        installed = [str(v) for v in solcx.get_installed_solc_versions()]
        if SOLC_VERSION not in installed:
            print(f"  installing solc {SOLC_VERSION} (one-off download)...")
            solcx.install_solc(SOLC_VERSION)
        compiled = solcx.compile_source(
            CONTRACT_SOURCE.read_text(encoding="utf-8"),
            output_values=["abi", "bin"],
            solc_version=SOLC_VERSION,
            optimize=True,
            optimize_runs=200,
        )
    except Exception as exc:
        raise ChainError(f"solc compilation failed: {exc}") from exc

    key = next((k for k in compiled if k.endswith(f":{CONTRACT_NAME}")), None)
    if key is None:
        raise ChainError(f"{CONTRACT_NAME} not found in compiler output")

    artifact = {
        "contractName": CONTRACT_NAME,
        "solcVersion": SOLC_VERSION,
        "abi": compiled[key]["abi"],
        "bytecode": compiled[key]["bin"],
        "sourceSha256": sha256_bytes(CONTRACT_SOURCE.read_bytes()),
    }
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return artifact


def load_artifact() -> dict[str, Any]:
    art_path = _get_artifact_path()
    if not art_path.exists():
        raise ChainError(
            f"no compiled artifact at {art_path}. Run: python -m src.main deploy"
        )
    return json.loads(art_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Real EVM client
# ---------------------------------------------------------------------------


def _raw_tx_bytes(signed: Any) -> bytes:
    """Extract raw transaction bytes across web3.py versions.

    web3 v6 exposes ``rawTransaction``; v7 renamed it ``raw_transaction``.
    """
    for attribute in ("raw_transaction", "rawTransaction"):
        value = getattr(signed, attribute, None)
        if value is not None:
            return value
    raise ChainError(
        "could not read raw transaction bytes from the signed transaction "
        "(unexpected web3.py version)"
    )


class EvmChainClient:
    """web3.py client for the deployed registry."""

    simulated = False

    def __init__(self, settings: Settings, *, require_signer: bool = True) -> None:
        try:
            from web3 import Web3
        except ImportError as exc:
            raise ChainError("web3 is not installed (pip install web3)") from exc

        self.settings = settings
        self.network = settings.chain_name
        self.chain_id = settings.chain_id

        if not settings.rpc_url:
            raise ChainError("RPC_URL is not set")

        self.w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 60}))
        self._install_poa_middleware()

        if not self.w3.is_connected():
            raise ChainError(
                f"cannot reach the RPC endpoint at {settings.rpc_url}. Check the URL "
                "and your network connection."
            )

        actual = self.w3.eth.chain_id
        if actual != settings.chain_id:
            raise ChainError(
                f"chain id mismatch: RPC reports {actual} but CHAIN_ID is "
                f"{settings.chain_id}. Fix .env so the two agree - anchoring to the "
                "wrong chain would silently produce unverifiable records."
            )

        self.artifact = load_artifact()
        self.account = None
        if require_signer:
            self.account = self._load_account()

        self.contract = None
        if settings.contract_address:
            self.contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(settings.contract_address),
                abi=self.artifact["abi"],
            )

    def _install_poa_middleware(self) -> None:
        """Tolerate chains whose ``extraData`` exceeds 32 bytes.

        Harmless on chains that do not need it, and prevents an obscure
        ExtraDataLengthError on those that do.
        """
        try:  # web3 v7
            from web3.middleware import ExtraDataToPOAMiddleware

            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            return
        except Exception:
            pass
        try:  # web3 v6
            from web3.middleware import geth_poa_middleware

            self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        except Exception:
            pass

    def _load_account(self):
        from eth_account import Account

        key = self.settings.private_key.strip()
        if not key:
            raise ChainError(
                "PRIVATE_KEY is not set. Use a burner wallet funded from a Base "
                "Sepolia faucet - never a key holding real assets."
            )
        if not key.startswith("0x"):
            key = "0x" + key
        try:
            return Account.from_key(key)
        except Exception as exc:
            raise ChainError(f"PRIVATE_KEY is not a valid private key: {exc}") from exc

    # -- helpers -----------------------------------------------------------

    def _require_contract(self):
        if self.contract is None:
            raise ChainError(
                "CONTRACT_ADDRESS is not set. Deploy first with "
                "'python -m src.main deploy', then put the address in .env"
            )
        return self.contract

    @staticmethod
    def _to_bytes32(data_hash: str) -> bytes:
        text = data_hash[2:] if data_hash.startswith("0x") else data_hash
        raw = bytes.fromhex(text)
        if len(raw) != 32:
            raise ChainError(f"expected a 32-byte hash, got {len(raw)} bytes")
        return raw

    def balance_eth(self) -> float:
        if self.account is None:
            return 0.0
        wei = self.w3.eth.get_balance(self.account.address)
        return wei / 1e18

    def _send(self, tx: dict[str, Any]) -> Any:
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(_raw_tx_bytes(signed))
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        if receipt.get("status") != 1:
            raise ChainError(f"transaction reverted on-chain: {tx_hash.hex()}")
        return receipt

    # -- operations --------------------------------------------------------

    def deploy(self) -> tuple[str, str]:
        """Deploy the registry. Returns ``(address, tx_hash)``."""
        factory = self.w3.eth.contract(
            abi=self.artifact["abi"], bytecode=self.artifact["bytecode"]
        )
        tx = factory.constructor().build_transaction(
            {
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "chainId": self.chain_id,
            }
        )
        receipt = self._send(tx)
        address = self.w3.to_checksum_address(receipt["contractAddress"])
        self.contract = self.w3.eth.contract(address=address, abi=self.artifact["abi"])
        return address, receipt["transactionHash"].hex()

    def register(self, data_hash: str, source_url: str) -> AnchorResult:
        contract = self._require_contract()
        raw_hash = self._to_bytes32(data_hash)
        function = contract.functions.register(raw_hash, source_url)

        # Simulate first: a revert here is almost always AlreadyRegistered, and
        # catching it before paying gas allows a precise message.
        try:
            function.call({"from": self.account.address})
        except Exception as exc:
            message = str(exc)
            if "AlreadyRegistered" in message or "already" in message.lower():
                raise ChainError(
                    "this exact verification hash is already anchored on-chain. "
                    "The registry is append-only and first-write-wins, so it "
                    "cannot be overwritten. Re-run 'verify' to inspect the "
                    "existing record."
                ) from exc
            raise ChainError(f"the transaction would revert: {message}") from exc

        tx = function.build_transaction(
            {
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "chainId": self.chain_id,
            }
        )
        # A modest buffer over the estimate: the estimate is made against the
        # pending state, and a competing transaction can shift real cost.
        if "gas" in tx:
            tx["gas"] = int(tx["gas"] * 1.25)

        receipt = self._send(tx)
        block = self.w3.eth.get_block(receipt["blockNumber"])
        tx_hash = receipt["transactionHash"].hex()
        if not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash

        return AnchorResult(
            data_hash=data_hash,
            tx_hash=tx_hash,
            block_number=int(receipt["blockNumber"]),
            block_timestamp=int(block["timestamp"]),
            contract_address=contract.address,
            submitter=self.account.address,
            chain_id=self.chain_id,
            network=self.network,
            gas_used=int(receipt.get("gasUsed", 0)),
            explorer_url=self.settings.tx_url(tx_hash),
        )

    def lookup(self, data_hash: str) -> ChainRecord:
        contract = self._require_contract()
        exists, submitter, timestamp, block_number, url_hash = contract.functions.verify(
            self._to_bytes32(data_hash)
        ).call()
        return ChainRecord(
            exists=bool(exists),
            submitter=str(submitter),
            timestamp=int(timestamp),
            block_number=int(block_number),
            url_hash=url_hash.hex() if hasattr(url_hash, "hex") else str(url_hash),
        )

    def matches_url(self, data_hash: str, source_url: str) -> bool:
        contract = self._require_contract()
        return bool(
            contract.functions.matchesUrl(self._to_bytes32(data_hash), source_url).call()
        )

    def describe(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "chain_id": self.chain_id,
            "rpc_url": self.settings.rpc_url,
            "contract_address": self.settings.contract_address,
            "signer": self.account.address if self.account else "",
            "simulated": False,
        }


# ---------------------------------------------------------------------------
# Mock client for --dry-run
# ---------------------------------------------------------------------------


class MockChainClient:
    """Local stand-in for the chain, used by ``--dry-run``.

    Exists so the pipeline can be rehearsed end to end without spending faucet
    funds or waiting on a testnet, and so the offline test suite can exercise
    the anchoring path. It reproduces the contract's semantics that actually
    matter - first-write-wins, an immutable append-only store, a recorded
    submitter - so a dry run fails in the same places a real run would.

    Records written here are marked ``"simulated": true`` in the payload's
    anchor block, so a simulated record can never be mistaken for a real one.
    """

    simulated = True

    def __init__(self, settings: Settings, path: str | Path | None = None) -> None:
        self.settings = settings
        self.network = f"{settings.chain_name}-simulated"
        self.chain_id = settings.chain_id
        self.path = Path(path or (settings.root / "localchain.json"))
        self._state: dict[str, Any] = {"records": {}, "head": 0}
        if self.path.exists():
            try:
                self._state = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        self._state.setdefault("records", {})
        self._state.setdefault("head", 0)

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    @staticmethod
    def _url_hash(url: str) -> str:
        """keccak256 of the URL when web3 is available, else a labelled SHA-256.

        The mock also keeps the plaintext URL, so URL checking here compares
        strings directly and does not depend on this value.
        """
        try:
            from web3 import Web3

            return Web3.keccak(text=url).hex()
        except Exception:
            return "0x" + sha256_bytes(url.encode("utf-8"))

    def register(self, data_hash: str, source_url: str) -> AnchorResult:
        import time

        key = data_hash.lower()
        if key in self._state["records"]:
            raise ChainError(
                "this verification hash is already anchored in the simulated "
                "chain (first-write-wins, exactly as the real contract behaves). "
                f"Delete {self.path.name} to reset the simulation."
            )

        self._state["head"] = int(self._state["head"]) + 1
        now = int(time.time())
        submitter = "0x" + "11" * 20
        entry = {
            "data_hash": key,
            "source_url": source_url,
            "url_hash": self._url_hash(source_url),
            "submitter": submitter,
            "timestamp": now,
            "block_number": self._state["head"],
        }
        self._state["records"][key] = entry
        self._save()

        return AnchorResult(
            data_hash=data_hash,
            tx_hash="0x" + sha256_bytes(f"{key}{now}".encode())[:64],
            block_number=entry["block_number"],
            block_timestamp=now,
            contract_address="0x" + "00" * 19 + "01",
            submitter=submitter,
            chain_id=self.chain_id,
            network=self.network,
            gas_used=0,
            explorer_url="",
            simulated=True,
        )

    def lookup(self, data_hash: str) -> ChainRecord:
        entry = self._state["records"].get(data_hash.lower())
        if not entry:
            return ChainRecord(exists=False)
        return ChainRecord(
            exists=True,
            submitter=entry["submitter"],
            timestamp=int(entry["timestamp"]),
            block_number=int(entry["block_number"]),
            url_hash=entry["url_hash"],
            extra={"source_url": entry.get("source_url", "")},
        )

    def matches_url(self, data_hash: str, source_url: str) -> bool:
        entry = self._state["records"].get(data_hash.lower())
        return bool(entry) and entry.get("source_url") == source_url

    def describe(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "chain_id": self.chain_id,
            "store": str(self.path),
            "records": len(self._state["records"]),
            "simulated": True,
        }


def build_chain_client(
    settings: Settings, *, dry_run: bool = False, require_signer: bool = True
) -> ChainClient:
    if dry_run:
        return MockChainClient(settings)
    return EvmChainClient(settings, require_signer=require_signer)
