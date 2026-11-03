# Base Sepolia Smart Contract Deployment & Release Guide

This guide details the procedure for compiling, validating, deploying, and verifying the `VerificationRegistry` (v3 interface) smart contract on the **Base Sepolia** Ethereum Layer-2 testnet.

> [!CRITICAL]
> **Current Release State:** The `VerificationRegistry` contract has been compiled and rigorously tested against an **in-process EVM** (`tests/test_registry_evm.py`), but **it has not been deployed to the public Base Sepolia testnet**.
> 
> Compilation and local EVM testing are NOT a public deployment. No blockchain transactions have been executed, and no testnet funds have been spent. Public deployment is a deliberate manual operation.

---

## 1. Contract Specifications & Interface Version

| Property | Value | Notes |
|---|---|---|
| **Contract Name** | `VerificationRegistry` | Defined in `contracts/VerificationRegistry.sol` |
| **Solidity Version** | `0.8.24` (pragma `^0.8.20`) | Py-solc-x downloads official solc 0.8.24 binary |
| **EVM Target** | `cancun` / default | Standard EVM compatibility |
| **Optimizer** | Enabled (`runs: 200`) | Standard configuration |
| **Interface Revision** | **v3** (`registryVersion() == 3`) | Superset of v2: adds Merkle-batch anchoring (`registerBatch`) |
| **URL Commitment** | `keccak256(bytes(url))` | Plaintext URLs are **never** transmitted on-chain |
| **Storage Packing** | 2 slots per record | Submitter (20B) + timestamp (6B) + block (6B) in slot 1 via `uint48` |
| **Governance / Admin** | **None** | No owner, no upgrade proxy, no pause, no deletion |

---

## 2. Distinction Between Registry Interfaces

* **Registry v1 (Deprecated):** Took plaintext URLs as calldata (`register(bytes32,string)`) and emitted them in events. Incompatible with this build.
* **Registry v2:** Replaced plaintext URLs with `bytes32 urlHash` commitment. Added `registryVersion() == 2`.
* **Registry v3 (Current):** Preserves all v2 selectors (`register`, `verify`, `matchesUrlHash`) and adds RFC 6962 Merkle-batch anchoring (`registerBatch`, `verifyBatch`, `totalBatches`). Returns `registryVersion() == 3`.

---

## 3. Pre-Deployment Checklist

Before deploying to Base Sepolia, verify each item:

- [ ] **Contract Source Integrity**: Verify `contracts/VerificationRegistry.sol` exists and passes hermetic compilation.
- [ ] **Burner Wallet Prepared**: Generate a dedicated, isolated testnet burner wallet. **Never use a private key that holds mainnet assets or identity credentials.**
- [ ] **Base Sepolia RPC Endpoint**: Confirm target RPC URL (default `https://sepolia.base.org`).
- [ ] **Chain ID Validation**: Confirm Base Sepolia chain ID is `84532`. The client refuses to connect if the RPC reports a different ID.
- [ ] **Testnet ETH Acquired**: Obtain testnet ETH through an official faucet (deployment requires approximately 0.002 to 0.005 ETH for gas).

---

## 4. Official Testnet Faucet Resources

Acquire Base Sepolia testnet ETH exclusively from reputable, official sources:

1. **Coinbase Developer Platform Faucet**:
   https://portal.cdp.coinbase.com/products/faucet (Provides Base Sepolia ETH directly).
2. **Superchain Faucet (Optimism / Base)**:
   https://console.optimism.io/faucet (Sign in with GitHub or Connect Wallet).
3. **Alchemy Base Sepolia Faucet**:
   https://www.alchemy.com/faucets/base-sepolia (Requires free Alchemy login).
4. **QuickNode Base Sepolia Faucet**:
   https://faucet.quicknode.com/base/sepolia

---

## 5. Local Compilation & Artifact Verification

Compile the contract locally without network access or gas expenditure:

```bash
python -m src.main deploy --compile-only --force-compile
```

**Expected output:**
```text
Compiler:              solc 0.8.24
Optimization:          runs=200
Source SHA-256:        <64-hex-digest>
Artifact written to:   contracts/build/VerificationRegistry.json
Interface version:     3 (Merkle batch supported)
```

Inspect the artifact to verify ABI and bytecode consistency:
* File location: `contracts/build/VerificationRegistry.json`
* Contains `abi` array with selectors for `register(bytes32,bytes32)`, `registerBatch(bytes32,uint32)`, and `registryVersion()`.

---

## 6. Target Environment Configuration (`.env`)

Configure the deployment environment variables in `.env` (git-ignored, never commit):

```ini
# Base Sepolia Network Configuration
RPC_URL=https://sepolia.base.org
CHAIN_ID=84532
CHAIN_NAME=base-sepolia
EXPLORER_BASE=https://sepolia.basescan.org

# Deployer Burner Wallet (DO NOT USE MAINNET KEYS)
PRIVATE_KEY=0x<your_burner_private_key_here>

# Left blank until deployment is completed
CONTRACT_ADDRESS=
```

---

## 7. Deployment Execution

Execute the deployment command. Note that `--yes` is required to authorise spending testnet gas:

```bash
python -m src.main deploy --yes --save
```

* `--yes`: Explicit user confirmation to spend testnet gas.
* `--save`: Automatically writes the resulting contract address into `.env` under `CONTRACT_ADDRESS`.

**Expected output:**
```text
Connected to:          base-sepolia (chain id 84532)
Deployer address:      0x<DeployerAddress>
Deployer balance:      0.0500 ETH
Deploying VerificationRegistry (v3)...
Transaction hash:      0x<TxHash>
Waiting for 1 block confirmation...
[OK] Contract deployed at: 0x<DeployedContractAddress>
Gas used:              684,210
Updated .env with CONTRACT_ADDRESS=0x<DeployedContractAddress>
```

---

## 8. Post-Deployment Verification (Read-Only)

Verify the deployed contract using read-only JSON-RPC queries (zero gas cost):

```bash
# 1. Run the system doctor
python -m src.main doctor

# Expected report:
#   chain:                 base-sepolia (id 84532)
#   CONTRACT_ADDRESS:      0x<DeployedAddress>
#   registry interface:    v3 (Merkle-batch supported)
#   [OK] contract is reachable and compatible
```

Alternatively, query `registryVersion()` directly via Web3 or `cast`:
```bash
cast call 0x<DeployedContractAddress> "registryVersion()(uint8)" --rpc-url https://sepolia.base.org
# Returns: 3
```

---

## 9. Block Explorer Verification (BaseScan)

To make the contract source verifiable and readable by the public on BaseScan:

1. Visit [BaseScan Sepolia](https://sepolia.basescan.org/address/0x<DeployedContractAddress>#code).
2. Click **Verify and Publish**.
3. Select:
   * **Compiler Type**: Single File / Standard JSON.
   * **Compiler Version**: `v0.8.24+commit.e11b9ed9`.
   * **Open Source License Type**: MIT License (SPDX).
4. Optimization:
   * **Optimization**: Yes.
   * **Runs**: `200`.
5. Paste the complete source code from `contracts/VerificationRegistry.sol`.
6. Submit and confirm verification.

---

## 10. Operational Testing: Anchoring & Verification

Once deployed, run real testnet operations:

### Single Record Anchoring
```bash
# Register a test case and anchor on Base Sepolia
python -m src.main register \
    --image tests/data/query.png \
    --fixture tests/data/candidates.json \
    --engine stub \
    --allow-offline-stub

# Verify the anchored record against the live contract
python -m src.main verify --record output/verification.json
```

### Merkle-Batch Anchoring (v3 Feature)
```bash
# 1. Seal multiple records without immediate anchoring
python -m src.main register --image doc1.png --fixture c1.json --engine stub --allow-offline-stub --anchor-mode batch --output out/r1.json
python -m src.main register --image doc2.png --fixture c2.json --engine stub --allow-offline-stub --anchor-mode batch --output out/r2.json

# 2. Anchor the entire batch in ONE transaction
python -m src.main anchor-batch out/r1.json out/r2.json

# 3. Verify inclusion proofs
python -m src.main verify --record out/r1.json
```

---

## 11. Rollback & Key Management

* **No Contract Proxy**: By design, `VerificationRegistry` contains no administrative proxy or self-destruct mechanism.
* **Rolling Back**: If a contract update is required, deploy a new instance and update `CONTRACT_ADDRESS` in `.env`. Historical records remain permanently verifiable on their respective historical contracts.
* **Key Safety**: After deployment and initial verification, remove the `PRIVATE_KEY` from `.env` if only read-only verifications will be conducted. Verifications never require a private key or gas.
