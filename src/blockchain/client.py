"""
Blockchain layer: compile, deploy, anchor, and look up verification hashes.

CHAIN CHOICE (Base Sepolia)
===========================
Base Sepolia is an OP-Stack Ethereum L2 testnet. It was chosen over Polygon
Amoy and Ethereum Sepolia for three practical reasons: its faucets are the most
reliable of the three, block times are ~2s so a demo does not stall waiting for
confirmation, and BaseScan renders the event log legibly.

Nothing here is Base-specific. It is a standard EVM chain reached over JSON-RPC,
so pointing ``RPC_URL``, ``CHAIN_ID`` and ``EXPLORER_BASE`` at another EVM chain
or a local node is a configuration change, not a code change.

PRIVACY OF THE SOURCE URL
=========================
The registry (interface v2) receives only ``keccak256(url)``, computed here.
The plaintext URL is never placed in calldata, storage or events. The local
record still contains the URL, so anyone holding the record can verify it
against the on-chain commitment. (The commitment is not secret against
guessing, and it does not prove the URL is authentic - see the README.)

WEB3 VERSION
============
Developed and tested against web3.py 7.x (7.16 at the time of writing) using the
v7 names (``raw_transaction``, ``ExtraDataToPOAMiddleware``). web3.py 6 is no
longer supported by this client.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..config import PROJECT_ROOT, Settings
from ..evidence.hashing import sha256_bytes

__all__ = [
    "ChainError",
    "IncompatibleContractError",
    "REGISTRY_VERSION",
    "MIN_REGISTRY_VERSION",
    "BatchRecord",
    "url_commitment",
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

# Interface revisions. v1 took the plaintext URL as calldata and emitted it in an
# event; v2 takes only a keccak256 commitment; v3 is a strict superset of v2 that
# adds Merkle-batch anchoring. The client works with v2 and v3 contracts; batch
# operations need v3.
REGISTRY_VERSION = 3
MIN_REGISTRY_VERSION = 2


class ChainError(RuntimeError):
    """A blockchain operation failed (or could not be completed)."""


class IncompatibleContractError(ChainError):
    """The configured address does not host a compatible registry (v2)."""


def url_commitment(url: str) -> str:
    """``0x``-prefixed keccak256 of the exact UTF-8 bytes of *url*.

    The single definition shared by the client, the mock and any verifier. The
    URL is committed byte-for-byte: no normalisation, trimming or case folding,
    so ``http://a/`` and ``http://a`` are different commitments.
    """
    if not isinstance(url, str):
        raise ChainError("source URL must be a string")
    try:
        from eth_utils.crypto import keccak
    except ImportError as exc:  # pragma: no cover - web3 depends on eth-utils
        raise ChainError("eth-utils is required to compute URL commitments") from exc
    try:
        raw = url.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ChainError("source URL is not valid Unicode text") from exc
    return "0x" + keccak(raw).hex()


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
    url_commitment: str = ""
    registry_version: int = REGISTRY_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "chain_id": int(self.chain_id),
            "contract_address": self.contract_address,
            "registry_version": int(self.registry_version),
            "tx_hash": self.tx_hash,
            "block_number": int(self.block_number),
            "block_timestamp": int(self.block_timestamp),
            "submitter": self.submitter,
            "url_commitment": self.url_commitment,
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


@dataclass
class BatchRecord:
    """What the chain says about a Merkle batch root."""

    exists: bool
    submitter: str = ""
    timestamp: int = 0
    block_number: int = 0
    size: int = 0


class ChainClient(Protocol):
    network: str
    chain_id: int
    simulated: bool

    def register(self, data_hash: str, source_url: str) -> AnchorResult: ...
    def lookup(self, data_hash: str) -> ChainRecord: ...
    def matches_url(self, data_hash: str, source_url: str) -> bool: ...
    def register_batch(self, root: str, size: int) -> AnchorResult: ...
    def lookup_batch(self, root: str) -> BatchRecord: ...
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

    A cached artifact built from a different source (or an older interface) is
    rejected: it would otherwise be deployed or used silently.
    """
    art_path = _get_artifact_path()
    if art_path.exists() and not force:
        artifact = load_artifact()
        if _artifact_matches_source(artifact):
            return artifact

    if not CONTRACT_SOURCE.exists():
        raise ChainError(f"contract source missing: {CONTRACT_SOURCE}")

    try:
        import solcx
    except ImportError as exc:
        raise ChainError(
            "py-solc-x is not installed (pip install py-solc-x), and no usable "
            f"prebuilt artifact was found at {art_path}"
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
        "registryVersion": REGISTRY_VERSION,
        "abi": compiled[key]["abi"],
        "bytecode": compiled[key]["bin"],
        "sourceSha256": sha256_bytes(_normalised_source()),
    }
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return artifact


def _normalised_source() -> bytes:
    """Source bytes with line endings normalised, so Git autocrlf cannot change the hash."""
    return CONTRACT_SOURCE.read_bytes().replace(b"\r\n", b"\n")


def _artifact_matches_source(artifact: dict[str, Any]) -> bool:
    """True if the cached artifact was built from the current source.

    Artifacts without ``sourceSha256`` (hand-made, or from tests) are trusted;
    a recorded hash that disagrees means the artifact is stale.
    """
    recorded = artifact.get("sourceSha256")
    if not recorded or not CONTRACT_SOURCE.exists():
        return True
    return recorded == sha256_bytes(_normalised_source())


def load_artifact() -> dict[str, Any]:
    art_path = _get_artifact_path()
    if not art_path.exists():
        raise ChainError(f"no compiled artifact at {art_path}. Run: python -m src.main deploy --compile-only")
    try:
        return json.loads(art_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ChainError(f"compiled artifact at {art_path} is not valid JSON") from exc


# ---------------------------------------------------------------------------
# Real EVM client
# ---------------------------------------------------------------------------


_ALREADY_ANCHORED = (
    "this exact verification hash is already anchored on-chain. The registry is "
    "append-only and first-write-wins, so it cannot be overwritten. Re-run "
    "'verify' to inspect the existing record."
)
# 4-byte selector of the custom error AlreadyRegistered(bytes32,uint48,address)
_ALREADY_SELECTOR = "b3dd9787"


def _short(exc: BaseException, limit: int = 240) -> str:
    """One-line, bounded description of an upstream error (no response bodies)."""
    text = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {text[:limit]}"


def _redact_url(url: str) -> str:
    """Show only scheme and host of an RPC URL: path, query and userinfo often hold API keys."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
    except ValueError:
        return "(unparseable URL)"
    return f"{parts.scheme}://{host}"


def _hex0x(value: Any) -> str:
    text = value.hex() if hasattr(value, "hex") else str(value)
    return text if text.startswith("0x") else "0x" + text


def _raw_tx_bytes(signed: Any) -> bytes:
    """Raw bytes of a signed transaction (eth-account 0.13+ / web3.py 7 attribute name)."""
    value = getattr(signed, "raw_transaction", None)
    if value is None:
        raise ChainError(
            "could not read raw transaction bytes from the signed transaction "
            "(unsupported eth-account / web3.py version; web3.py 7.x is required)"
        )
    return value


class EvmChainClient:
    """web3.py client for the deployed registry (interface v2)."""

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

        try:
            connected = self.w3.is_connected()
        except Exception:  # noqa: BLE001
            connected = False
        if not connected:
            raise ChainError(
                f"cannot reach the RPC endpoint at {_redact_url(settings.rpc_url)}. "
                "Check the URL and your network connection."
            )

        try:
            actual = self.w3.eth.chain_id
        except Exception as exc:  # noqa: BLE001
            raise ChainError(f"RPC did not report a chain id: {_short(exc)}") from exc
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
        self.registry_version = 0  # set by check_compatibility() once a contract is attached
        if settings.contract_address:
            if not self.w3.is_address(settings.contract_address):
                raise ChainError("CONTRACT_ADDRESS is not a valid address")
            self.contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(settings.contract_address),
                abi=self.artifact["abi"],
            )
            self.check_compatibility()

    def check_compatibility(self) -> int:
        """Confirm the address hosts registry interface v2; return its version.

        A v1 deployment (plaintext-URL interface) has no ``registryVersion``,
        so the call reverts. Without this check the client would send a v2
        ``register`` call to it and fail obscurely - or, for reads, report a
        misleading "not anchored".
        """
        contract = self._require_contract()
        try:
            code = self.w3.eth.get_code(contract.address)
        except Exception as exc:  # noqa: BLE001
            raise ChainError(f"could not read contract code: {_short(exc)}") from exc
        if not code:
            raise IncompatibleContractError(
                f"no contract code at {contract.address} on this chain. Check CONTRACT_ADDRESS and CHAIN_ID."
            )
        try:
            version = int(contract.functions.registryVersion().call())
        except Exception as exc:  # noqa: BLE001
            raise IncompatibleContractError(
                f"the contract at {contract.address} does not expose registryVersion(): "
                "it is an older (v1, plaintext-URL) registry or not a registry at all. "
                "Records anchored there cannot be checked through this build's v2 "
                "interface; deploy the v2 contract manually (see README)."
            ) from exc
        if not MIN_REGISTRY_VERSION <= version <= REGISTRY_VERSION:
            raise IncompatibleContractError(
                f"registry interface version {version} is not supported "
                f"(this build supports {MIN_REGISTRY_VERSION}-{REGISTRY_VERSION})"
            )
        self.registry_version = version
        return version

    def _install_poa_middleware(self) -> None:
        """Tolerate chains whose ``extraData`` exceeds 32 bytes (web3.py 7 API)."""
        from web3.middleware import ExtraDataToPOAMiddleware

        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    def _load_account(self):
        from eth_account import Account

        key = self.settings.private_key.strip()
        if not key:
            raise ChainError(
                "PRIVATE_KEY is not set. Use a burner wallet funded from a testnet "
                "faucet - never a key holding real assets."
            )
        if not key.startswith("0x"):
            key = "0x" + key
        try:
            return Account.from_key(key)
        except Exception as exc:
            # Do not echo the library message: it can include key material.
            raise ChainError("PRIVATE_KEY is not a valid private key") from exc

    # -- helpers -----------------------------------------------------------

    def _require_contract(self):
        if self.contract is None:
            raise ChainError(
                "CONTRACT_ADDRESS is not set. Deploy the v2 registry manually "
                "(see README > Manual deployment), then put the address in .env"
            )
        return self.contract

    @staticmethod
    def _to_bytes32(data_hash: str) -> bytes:
        text = data_hash[2:] if data_hash.startswith("0x") else data_hash
        try:
            raw = bytes.fromhex(text)
        except ValueError as exc:
            raise ChainError("expected a hex-encoded 32-byte hash") from exc
        if len(raw) != 32:
            raise ChainError(f"expected a 32-byte hash, got {len(raw)} bytes")
        return raw

    def balance_eth(self) -> float:
        if self.account is None:
            return 0.0
        wei = self.w3.eth.get_balance(self.account.address)
        return wei / 1e18

    def _send(self, tx: dict[str, Any]) -> Any:
        if self.account is None:
            raise ChainError("a signer (PRIVATE_KEY) is required to send transactions")
        try:
            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(_raw_tx_bytes(signed))
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        except ChainError:
            raise
        except Exception as exc:  # noqa: BLE001 - includes TimeExhausted and RPC errors
            raise ChainError(f"transaction could not be confirmed: {_short(exc)}") from exc
        if receipt.get("status") != 1:
            raise ChainError(f"transaction reverted on-chain: {_hex0x(tx_hash)}")
        return receipt

    # -- operations --------------------------------------------------------

    def deploy(self) -> tuple[str, str]:
        """Deploy the registry. Returns ``(address, tx_hash)``. Spends gas."""
        if self.account is None:
            raise ChainError("a signer (PRIVATE_KEY) is required to deploy")
        factory = self.w3.eth.contract(abi=self.artifact["abi"], bytecode=self.artifact["bytecode"])
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
        return address, _hex0x(receipt["transactionHash"])

    def register(self, data_hash: str, source_url: str) -> AnchorResult:
        """Anchor *data_hash* with the keccak256 commitment of *source_url*.

        Only the commitment is transmitted; the URL never leaves this process.
        """
        contract = self._require_contract()
        if self.account is None:
            raise ChainError("a signer (PRIVATE_KEY) is required to register")
        raw_hash = self._to_bytes32(data_hash)
        commitment = url_commitment(source_url)
        function = contract.functions.register(raw_hash, self._to_bytes32(commitment))

        # Check for a duplicate explicitly: relying on the revert text is
        # fragile because custom errors surface as raw selectors on many RPCs.
        if self.lookup(data_hash).exists:
            raise ChainError(_ALREADY_ANCHORED)

        # Simulate before paying gas so a revert gets a precise message.
        try:
            function.call({"from": self.account.address})
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "AlreadyRegistered" in message or _ALREADY_SELECTOR in message.lower():
                raise ChainError(_ALREADY_ANCHORED) from exc
            raise ChainError(f"the transaction would revert: {_short(exc)}") from exc

        try:
            tx = function.build_transaction(
                {
                    "from": self.account.address,
                    "nonce": self.w3.eth.get_transaction_count(self.account.address),
                    "chainId": self.chain_id,
                }
            )
        except Exception as exc:  # noqa: BLE001
            raise ChainError(f"could not build the transaction: {_short(exc)}") from exc
        # A modest buffer over the estimate: a competing transaction can shift real cost.
        if "gas" in tx:
            tx["gas"] = int(tx["gas"] * 1.25)

        receipt = self._send(tx)
        try:
            block = self.w3.eth.get_block(receipt["blockNumber"])
        except Exception as exc:  # noqa: BLE001
            raise ChainError(f"could not read the anchoring block: {_short(exc)}") from exc

        return AnchorResult(
            data_hash=data_hash,
            tx_hash=_hex0x(receipt["transactionHash"]),
            block_number=int(receipt["blockNumber"]),
            block_timestamp=int(block["timestamp"]),
            contract_address=contract.address,
            submitter=self.account.address,
            chain_id=self.chain_id,
            network=self.network,
            gas_used=int(receipt.get("gasUsed", 0)),
            explorer_url=self.settings.tx_url(_hex0x(receipt["transactionHash"])),
            url_commitment=commitment,
            registry_version=self.registry_version,
        )

    def lookup(self, data_hash: str) -> ChainRecord:
        contract = self._require_contract()
        key = self._to_bytes32(data_hash)
        try:
            exists, submitter, timestamp, block_number, url_hash = contract.functions.verify(key).call()
        except Exception as exc:  # noqa: BLE001
            raise ChainError(f"chain lookup failed: {_short(exc)}") from exc
        return ChainRecord(
            exists=bool(exists),
            submitter=str(submitter),
            timestamp=int(timestamp),
            block_number=int(block_number),
            url_hash=_hex0x(url_hash),
        )

    def matches_url(self, data_hash: str, source_url: str) -> bool:
        """True/False if the commitment was checked; ``ChainError`` if it could not be.

        Never returns True for a check that did not run.
        """
        contract = self._require_contract()
        key = self._to_bytes32(data_hash)
        commitment = self._to_bytes32(url_commitment(source_url))
        try:
            return bool(contract.functions.matchesUrlHash(key, commitment).call())
        except Exception as exc:  # noqa: BLE001
            raise ChainError(f"URL commitment check failed: {_short(exc)}") from exc

    def _require_batch_support(self):
        contract = self._require_contract()
        if self.registry_version < 3:
            raise IncompatibleContractError(
                f"the contract at {contract.address} is registry v{self.registry_version}; Merkle-batch "
                "anchoring needs v3. Deploy the v3 contract manually (docs/DEPLOYMENT.md)."
            )
        return contract

    def register_batch(self, root: str, size: int) -> AnchorResult:
        """Anchor a Merkle root covering *size* records in a single transaction."""
        contract = self._require_batch_support()
        if self.account is None:
            raise ChainError("a signer (PRIVATE_KEY) is required to register")
        if not isinstance(size, int) or not 1 <= size < 2**32:
            raise ChainError("batch size must be between 1 and 2**32 - 1")
        raw_root = self._to_bytes32(root)
        if self.lookup_batch(root).exists:
            raise ChainError(_ALREADY_ANCHORED.replace("verification hash", "batch root"))
        function = contract.functions.registerBatch(raw_root, size)
        try:
            function.call({"from": self.account.address})
        except Exception as exc:  # noqa: BLE001
            raise ChainError(f"the transaction would revert: {_short(exc)}") from exc
        try:
            tx = function.build_transaction(
                {
                    "from": self.account.address,
                    "nonce": self.w3.eth.get_transaction_count(self.account.address),
                    "chainId": self.chain_id,
                }
            )
        except Exception as exc:  # noqa: BLE001
            raise ChainError(f"could not build the transaction: {_short(exc)}") from exc
        if "gas" in tx:
            tx["gas"] = int(tx["gas"] * 1.25)
        receipt = self._send(tx)
        try:
            block = self.w3.eth.get_block(receipt["blockNumber"])
        except Exception as exc:  # noqa: BLE001
            raise ChainError(f"could not read the anchoring block: {_short(exc)}") from exc
        tx_hash = _hex0x(receipt["transactionHash"])
        return AnchorResult(
            data_hash=root,
            tx_hash=tx_hash,
            block_number=int(receipt["blockNumber"]),
            block_timestamp=int(block["timestamp"]),
            contract_address=contract.address,
            submitter=self.account.address,
            chain_id=self.chain_id,
            network=self.network,
            gas_used=int(receipt.get("gasUsed", 0)),
            explorer_url=self.settings.tx_url(tx_hash),
            registry_version=self.registry_version,
        )

    def lookup_batch(self, root: str) -> BatchRecord:
        contract = self._require_batch_support()
        key = self._to_bytes32(root)
        try:
            exists, submitter, timestamp, block_number, size = contract.functions.verifyBatch(key).call()
        except Exception as exc:  # noqa: BLE001
            raise ChainError(f"batch lookup failed: {_short(exc)}") from exc
        return BatchRecord(bool(exists), str(submitter), int(timestamp), int(block_number), int(size))

    def describe(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "chain_id": self.chain_id,
            "rpc_url": _redact_url(self.settings.rpc_url),
            "contract_address": self.settings.contract_address,
            "signer": self.account.address if self.account else "",
            "registry_version": self.registry_version or REGISTRY_VERSION,
            "simulated": False,
        }


# ---------------------------------------------------------------------------
# Mock client for --dry-run
# ---------------------------------------------------------------------------


class MockChainClient:
    """Local stand-in for the chain, used by ``--dry-run``.

    NOT A BLOCKCHAIN. It is a JSON file. It exists so the pipeline can be
    rehearsed end to end without a wallet, gas or network, and so the offline
    test suite can exercise the anchoring path. It reproduces the contract
    semantics that matter - first-write-wins, append-only, URL stored only as a
    commitment - so a dry run fails in the same places a real run would.

    Everything it produces is labelled ``"simulated": true`` and its network
    name ends in ``-simulated``.
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
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._state = loaded
            except ValueError:
                pass
        if not isinstance(self._state.get("records"), dict):
            self._state["records"] = {}
        if not isinstance(self._state.get("head"), int):
            self._state["head"] = 0
        if not isinstance(self._state.get("batches"), dict):
            self._state["batches"] = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def register(self, data_hash: str, source_url: str) -> AnchorResult:
        import time

        key = data_hash.lower()
        if key in self._state["records"]:
            raise ChainError(
                "this verification hash is already anchored in the simulated "
                "chain (first-write-wins, exactly as the real contract behaves). "
                f"Delete {self.path.name} to reset the simulation."
            )

        commitment = url_commitment(source_url)
        self._state["head"] = int(self._state["head"]) + 1
        now = int(time.time())
        submitter = "0x" + "11" * 20
        entry = {
            "data_hash": key,
            "url_hash": commitment,
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
            url_commitment=commitment,
        )

    def register_batch(self, root: str, size: int) -> AnchorResult:
        import time

        key = root.lower()
        if not isinstance(size, int) or not 1 <= size < 2**32:
            raise ChainError("batch size must be between 1 and 2**32 - 1")
        if key in self._state["batches"]:
            raise ChainError(
                "this batch root is already anchored in the simulated chain "
                f"(first-write-wins). Delete {self.path.name} to reset the simulation."
            )
        self._state["head"] = int(self._state["head"]) + 1
        now = int(time.time())
        submitter = "0x" + "11" * 20
        entry = {
            "root": key,
            "size": size,
            "submitter": submitter,
            "timestamp": now,
            "block_number": self._state["head"],
        }
        self._state["batches"][key] = entry
        self._save()
        return AnchorResult(
            data_hash=root,
            tx_hash="0x" + sha256_bytes(f"batch{key}{now}".encode())[:64],
            block_number=entry["block_number"],
            block_timestamp=now,
            contract_address="0x" + "00" * 19 + "01",
            submitter=submitter,
            chain_id=self.chain_id,
            network=self.network,
            simulated=True,
        )

    def lookup_batch(self, root: str) -> BatchRecord:
        entry = self._state["batches"].get(root.lower())
        if not entry:
            return BatchRecord(exists=False)
        return BatchRecord(
            True, entry["submitter"], int(entry["timestamp"]), int(entry["block_number"]), int(entry["size"])
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
        )

    def matches_url(self, data_hash: str, source_url: str) -> bool:
        entry = self._state["records"].get(data_hash.lower())
        return bool(entry) and entry.get("url_hash") == url_commitment(source_url)

    def describe(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "chain_id": self.chain_id,
            "store": str(self.path),
            "records": len(self._state["records"]),
            "registry_version": REGISTRY_VERSION,
            "simulated": True,
        }


def build_chain_client(settings: Settings, *, dry_run: bool = False, require_signer: bool = True) -> ChainClient:
    if dry_run:
        return MockChainClient(settings)
    return EvmChainClient(settings, require_signer=require_signer)
