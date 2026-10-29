# Manual deployment and migration of the registry (interface v2)

> **Nothing in this repository has deployed a contract, sent a transaction or changed `.env`.** The v2
> contract was compiled and executed only on an in-process EVM (`tests/test_registry_evm.py`). Everything
> below is a procedure for *you* to run deliberately.

## What changed and why a new deployment is needed

| | v1 (previous) | v2 (this build) |
|---|---|---|
| `register` | `register(bytes32 dataHash, string sourceUrl)` | `register(bytes32 dataHash, bytes32 urlHash)` |
| URL on chain | plaintext in **calldata** and in the `Registered` **event**; hash in storage | **never**: only `keccak256(url)` is sent, stored and logged |
| Event | `Registered(dataHash, submitter, urlHash, string sourceUrl, timestamp)` | `Registered(dataHash, submitter, urlHash, timestamp)` |
| URL check | `matchesUrl(bytes32, string)` | `matchesUrlHash(bytes32, bytes32)` (the client hashes locally) |
| Version probe | none | `registryVersion()` returns `2` |
| Zero values | `ZeroHash` for the data hash | `ZeroHash` for either argument |

The function selector changed, so **a v1 deployment cannot accept v2 calls**, and the data it already
holds cannot be changed or hidden: a plaintext URL that was ever sent to a v1 contract remains in that
transaction's calldata and in its event log permanently. This build does **not** claim any old deployment
has the new privacy property.

`EvmChainClient` calls `registryVersion()` when it connects. An address that has no code, or whose contract
lacks that function (a v1 registry), raises `IncompatibleContractError`; `verify` then reports
**inconclusive (exit 6)** rather than "not anchored" or success.

## Historical records

* **Local integrity** of v1 records (schema `faceverify/v1`, algorithm `sha256-jcs-rfc8785`) is still
  verified, offline, with their original rules. See `docs/RECORD_FORMAT.md`.
* **Chain verification** of a record that was anchored on a v1 deployment cannot go through this build's
  v2 interface. Keep (or check out) the earlier release to look such records up, or re-register the claim
  against a v2 contract (this creates a *new* anchor with a new timestamp; it does not back-date anything).

## Procedure

1. **Compile (no network except a one-off solc download, no gas):**
   ```bash
   python -m src.main deploy --compile-only --force-compile
   ```
   Prints the solc version (0.8.24), interface version (v2) and the SHA-256 of the source
   (line endings normalised). The artifact is written to `contracts/build/` (git-ignored).
2. **Review** `contracts/VerificationRegistry.sol`. Consider an independent review before using it for
   anything beyond a testnet.
3. **Use a burner wallet** funded from the official faucet of the *testnet* you choose. Never a key that
   controls real assets. Put it in `.env` as `PRIVATE_KEY` (the file is git-ignored; never commit it).
4. **Deploy** — this spends testnet gas and creates a permanent public contract:
   ```bash
   python -m src.main deploy --yes --save
   ```
   Without `--yes` the command refuses. `--save` writes `CONTRACT_ADDRESS` into `.env`.
   Alternatively deploy with your own tooling from the artifact's ABI + bytecode and set `CONTRACT_ADDRESS`
   yourself.
5. **Check** the deployment read-only:
   ```bash
   python -m src.main doctor
   ```
   It should report `registry interface v2`.
6. **Verify the source on the block explorer** if you want others to be able to read it (explorer
   instructions vary; use the same compiler version and optimiser settings: 0.8.24, 200 runs).

## Chains

Nothing is Base-specific: `RPC_URL`, `CHAIN_ID`, `CHAIN_NAME`, `EXPLORER_BASE` select the chain, and the
client refuses to run if the RPC's chain id differs from `CHAIN_ID`. Check the current network and faucet
documentation at <https://docs.base.org/> before relying on a specific testnet.

## Rolling back

There is no upgrade or admin path by design. To "roll back", point `CONTRACT_ADDRESS` at a different
deployment. Records already anchored stay where they are.
