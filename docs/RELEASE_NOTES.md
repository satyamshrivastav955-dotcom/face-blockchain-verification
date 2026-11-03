# FaceProof v2.0.0 Release Notes

**Release Date:** 30 October 2026  
**Release Tag:** `v2.0.0` (Recommended)  
**Schema Version:** `faceverify/v2`  
**Registry Interface:** `v3` (Merkle-batch supported)  

FaceProof v2.0.0 is a major release transforming the original command-line prototype into a comprehensive, evidence-first image provenance platform. This release introduces a dual-engine computer vision architecture, an explainable three-tier evidence ladder, deterministic RFC 8785 canonical JSON sealing, privacy-preserving Keccak-256 URL commitments, and RFC 6962 Merkle-batch blockchain anchoring.

---

## 🌟 Key Highlights & New Capabilities

### 1. Dual-Engine Computer Vision Architecture
* **Permissive Default:** Integrated OpenCV YuNet detector and SFace recognizer (Apache-2.0 / MIT) running on CPU via OpenCV DNN.
* **Forensic Research Engine:** Optional support for SCRFD-10G (multi-scale 5-point landmark detection) and ArcFace (ResNet-50 / ResNet-100) via ONNX Runtime with CUDA 12 acceleration.
* **Prominence Subject Selection:** Implemented `sqrt(area) * centrality` ranking to eliminate the 2.4-percentage-point error rate observed with naive "largest face" heuristics on multi-face images.

### 2. Three-Tier Evidence Classification
* **Confirmed Face Match:** Facial embedding cosine similarity exceeds calibrated thresholds.
* **Confirmed Image Derivative (Geometric):** SIFT keypoints + Lowe ratio test + RANSAC homography estimation recovering crops, rotations, and mirroring ($\ge 25$ inliers, non-degenerate transform).
* **Confirmed Image Derivative (Perceptual):** 64-bit DCT perceptual hash (pHash distance $\le 12$).
* **Strict Semantic Honesty:** Image derivations are never promoted to face matches; unexecuted checks return exit code **6 (`inconclusive`)** rather than a pass.

### 3. C2PA Content Credentials Inspection
* Independent extraction and verification of signed C2PA manifests via `c2pa-python` on query and candidate images, reporting signer validity and generative-AI declarations.

### 4. Deterministic Sealing & Record Envelope (`faceverify/v2`)
* Standardized envelope structure separating the unanchored transaction metadata from the hashed payload.
* Deterministic canonicalization using a restricted profile of RFC 8785 (`sha256-jcs-rfc8785-restricted-v1`), enforcing safe 64-bit integer ranges and forbidding floats in hashed sections.
* Backward compatibility engine verifying legacy `faceverify/v1` records under their historical rules without re-interpretation.

### 5. Smart Contract Registry v3 (Solidity 0.8.24)
* **First-Write-Wins Guard:** Prevents hash overwriting or back-dating by adversaries.
* **Zero Admin Backdoors:** No owner address, no pause controls, and no upgrade proxy delegates.
* **URL Privacy via Keccak-256 Commitments:** Plaintext URLs are never passed in calldata or logged in events.
* **RFC 6962 Merkle-Batch Anchoring:** Anchors up to 1,000 records in a single on-chain transaction (`registerBatch`), reducing gas cost to ~74 gas per record with logarithmic inclusion proofs.

### 6. SSRF-Guarded Candidate Intake
* Socket-level IP pinning, manual redirect re-validation, private IP range blocks (RFC 1918, RFC 3927, IPv6 loopback, NAT64), and dimension caps (&le; 16,384 px, &le; 50 MP, &le; 25 MiB).

### 7. Local-First Web Application & Public Showcase
* **Local Web App (`web/` + `src/web/`):** React 19 + TypeScript + Vite frontend communicating with a loopback-only FastAPI backend with strict Host/Origin checking.
* **Public Static Showcase (`showcase/`):** Decoupled static presentation website prepared for GitHub Pages with zero backend dependencies or API key exposure.

---

## ⚠️ Known Boundaries & Current Limitations

1. **Smart Contract Deployment Status:** The `VerificationRegistry` v3 smart contract is compiled and tested on an in-process EVM (`tests/test_registry_evm.py`), but **has not been deployed publicly to the Base Sepolia testnet**. Deployment instructions are documented in `docs/BASE_SEPOLIA_RELEASE.md`.
2. **Model Licensing:** The permissive OpenCV Zoo models are Apache-2.0 / MIT. Pretrained ArcFace/SCRFD weights from InsightFace carry **non-commercial research restrictions**.
3. **Evaluation Boundaries:** Face benchmarks were measured exclusively on LFW (clean 10-fold accuracy 99.32%–99.65%). No benchmarks were conducted on IJB-C, CFP-FP, AgeDB, or demographic splits; no fairness claim is made.
4. **Geometric Verification Scope:** Geometric inlier validation was benchmarked on synthetic fixtures; real-world photographs with repetitive textures (architectural facades, repeated text) may produce false inliers.
5. **No Authentication on Local Web Server:** The FastAPI backend is designed strictly for local loopback use (`127.0.0.1`) and must never be bound to a public network interface.
6. **Repository License:** The repository does not currently include a root LICENSE file; third-party dependencies operate under their respective licenses.

---

## 📦 Upgrade & Migration Notes

* **From v1 Records:** Records sealed under `faceverify/v1` remain verifiable locally using `python -m src.main verify --record <file>`. Because the on-chain interface changed in v2/v3, v1 records cannot be verified against a v3 contract.
* **CLI Exit Codes:** Applications integrating with the CLI must handle exit code `6` (`inconclusive`), indicating that an RPC node or provider check could not be executed.
