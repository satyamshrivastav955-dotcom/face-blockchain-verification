# Changelog

All notable changes. Format follows [Keep a Changelog](https://keepachangelog.com/); this project follows
semantic versioning for its record schema and CLI exit codes (a breaking change to either bumps the major
version).

## [2.0.0] - 2026-10-30

### Breaking
* **Registry interface v2/v3.** The plaintext source URL is no longer sent on-chain: `register` takes
  `keccak256(url)` (`bytes32`). A v1 deployment is detected and rejected; records anchored on v1 cannot be
  chain-verified through this build. v3 adds Merkle-batch anchoring and is a strict superset of v2. **Neither
  is deployed.**
* **Record schema `faceverify/v2`** and algorithm label `sha256-jcs-rfc8785-restricted-v1` (the canonicalizer
  is a restricted RFC 8785 profile and is named as such). Records sealed by earlier builds still verify
  locally under their original rules.
* **Verification fails closed.** A failed or impossible chain/URL-commitment check is *inconclusive* (new exit
  code **6**), not a pass. Unknown integrity algorithms fail.
* `PUBLISH_PROVIDER` now defaults to `none`; external search and public upload need explicit consent flags.
* `deploy` refuses to spend gas without `--yes`.

### Added
* **Match outcomes:** `confirmed_face_match` vs `confirmed_image_derivative`, with wording that never promotes
  image similarity to a face match; deterministic candidate selection; `--require-face-match`.
* **Geometric verification** (SIFT + RANSAC) as a second derivative basis that recovers crops, rotations and
  mirrored copies; recorded with inlier counts.
* **C2PA Content Credentials** read on the source and matched images.
* **ArcFace/SCRFD engines** on ONNX Runtime (CUDA optional): `arcface-r50`, `arcface-r100`, `auto`. Per-engine
  thresholds; licence recorded in every record. Subject-face selection by prominence.
* **Merkle-batched anchoring** (RFC 6962): `register --anchor-mode batch`, `anchor-batch`, inclusion-proof
  verification.
* **SSRF-guarded fetching:** IP-pinned connections, redirect revalidation, size/pixel/time limits; bounded
  parallel candidate downloads.
* **Local web app** (FastAPI + React/TypeScript), `verify --json`, `verify --evidence-dir`,
  `purge-evidence`, `--minimal-evidence`.
* Benchmark harness (`scripts/benchmark_face.py`) with LFW results in `docs/results/`; checksum-pinned model
  fetchers; reproducible dependency constraints; CI workflow; documentation under `docs/`.

### Changed
* Secrets are never printed (`doctor` shows only "set (N chars)"); RPC URLs are reduced to scheme and host.
* Records no longer store a raw face-embedding hash under `embedding_sha256`; the field is
  `embedding_commitment_sha256` and is documented as a commitment, not anonymisation.
* Whole codebase formatted and linted uniformly (ruff: E, F, W, B, I, UP) and type-checked (mypy).

### Fixed
* A URL-commitment lookup failure was reported as success.
* Duplicate-registration detection relied on revert text that real RPCs do not provide.
* Candidate image paths from a search response could read local files; only the offline fixture may now.

### Not done
* No contract deployment; no face benchmark beyond LFW; geometric verification validated on synthetic images
  only; CI not yet run on GitHub; no `LICENSE` file (owner's decision).

## [1.0.0]
Initial command-line pipeline: YuNet + SFace, reverse-image search, local confirmation, hash anchoring.
