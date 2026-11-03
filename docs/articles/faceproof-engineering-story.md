---
title: "Beyond Reverse Image Search: Building FaceProof, an Evidence-First Image Provenance System"
subtitle: "How we combined local computer vision, deterministic canonicalization, and an EVM commitment registry to turn ephemeral search hits into verifiable cryptographic records."
published_date: "2026-10-30"
author: "FaceProof Engineering"
canonical_url: "https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/docs/articles/faceproof-engineering-story.md"
tags: ["ComputerVision", "Blockchain", "Python", "Cryptography", "Security", "Web3", "OpenSource"]
seo_description: "An in-depth technical case study on building FaceProof, an open-source image provenance system combining local facial biometrics, SSRF-guarded re-examination, canonical JSON hashing, and Base-compatible blockchain anchoring."
cover_image_description: "An architectural schema showing an image split into local biometric embeddings and SHA-256 canonical integrity digests anchored into an EVM Merkle tree."
---

# Beyond Reverse Image Search: Building FaceProof, an Evidence-First Image Provenance System

When an investigator, journalist, or engineer runs a reverse-image search on the modern web, the engine typically returns candidate links: thumbnails, page titles, and web addresses where visually related assets allegedly appear.

Under current practice, preserving that search outcome as "proof" relies on screenshots, bookmarking URLs, or saving local files. In an adversarial or fast-changing online environment, none of those techniques constitute reliable evidence:

1. **Search hits are ephemeral.** Web pages change, syndication networks overwrite assets, and hosting accounts get suspended. A link that existed in the morning may return HTTP 404 by evening.
2. **Search hits are uninspected leads, not findings.** Search engines match global descriptors or surrounding text, not audited facial landmarks. They regularly group visual analogues, unrelated memes, or generic stock templates under the same query.
3. **Screenshots lack cryptographic integrity.** A browser screenshot can be fabricated in seconds with standard developer inspection tools. It does not establish what byte stream was fetched, which IP address answered the TCP connection, or what mathematical similarity threshold was satisfied.

To bridge the gap between finding a candidate URL and producing an independently inspectable verification record, we built **FaceProof**.

FaceProof is an open-source image provenance system. It connects local computer vision inference, guarded candidate downloading, three-tiered evidence re-examination, deterministic canonical JSON hashing, and EVM blockchain commitments. This article describes the architectural decisions, cryptographic protocols, security threat models, and empirical benchmarks behind its implementation.

---

## 1. What FaceProof Is (and What It Is Not)

Before looking at the technical pipeline, we must establish an essential semantic boundary:

> **FaceProof is an image-provenance system, not a facial recognition or identity system.**

It does not maintain a database of human identities. It does not map faces to government names or user accounts. Instead, it measures whether a query image and a candidate image found on the web share verifiable geometric or facial visual properties, and anchors an immutable, timestamped record of that measurement onto a public ledger.

A blockchain commitment in FaceProof proves that **a specific canonical evidence payload existed and was anchored at or before a given block timestamp**. It does not prove that an external claim is true, that a third-party website is trustworthy, or who a photographed individual is in the real world. Treating visual similarity as identity verification is an engineering and ethical fallacy that FaceProof’s architecture explicitly rejects.

---

## 2. System Architecture: Operational Boundaries

FaceProof is structured around three distinct operational boundaries, ensuring that sensitive biometric data never leaks to public networks or distributed ledgers:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. LOCAL WORKSTATION BOUNDARY                                         │
│   Input Image ──► Face Detection (YuNet / SCRFD)                       │
│                     │                                                  │
│                     ├──► 5-Point Alignment (Umeyama Transform)         │
│                     └──► Face Embedding (SFace / ArcFace R50/R100)     │
│                            │                                           │
│                            └──► Subject Selection (Prominence Metric)  │
└─────────────────────────────┼──────────────────────────────────────────┘
                              │ Query URL / Image Hash
┌─────────────────────────────▼──────────────────────────────────────────┐
│ 2. THIRD-PARTY PROVIDER BOUNDARY (Explicit Consent Required)           │
│   Reverse Search (Google Lens / TinEye) ──► Candidate URLs (Leads)     │
└─────────────────────────────┬──────────────────────────────────────────┘
                              │ Untrusted Candidate URLs
┌─────────────────────────────▼──────────────────────────────────────────┐
│ 3. SSRF-GUARDED INTAKE & RE-EXAMINATION (Local)                        │
│   Candidate Downloads (IP-pinned, redirect-checked, size-bounded)      │
│     │                                                                  │
│     ├──► Tier 1: Biometric Cosine Similarity (Query vs Candidate)      │
│     ├──► Tier 2: SIFT + RANSAC Homography (Geometric Inliers)          │
│     ├──► Tier 3: 64-bit DCT Perceptual Hashing (pHash)                 │
│     └──► C2PA Manifest Evaluation (Content Credentials)                │
└─────────────────────────────┬──────────────────────────────────────────┘
                              │ Deterministic Payload
┌─────────────────────────────▼──────────────────────────────────────────┐
│ 4. CRYPTOGRAPHIC SEALING & LEDGER COMMITMENT                           │
│   Restricted RFC 8785 Canonical JSON ──► SHA-256 Verification Hash    │
│   Candidate Matched URL ───────────────► Keccak-256 URL Commitment     │
│                                            │                           │
│   Base Sepolia Smart Contract ◄────────────┴── Single or Merkle Batch  │
└────────────────────────────────────────────────────────────────────────┘
```

* **Local Workstation Boundary:** All computer vision inference—face detection, 5-point landmark detection, Umeyama affine alignment, and feature vector extraction—runs exclusively in local memory. The resulting floating-point embedding tensors exist only ephemerally in RAM. They are never written to disk, never cached, and never transmitted over network sockets.
* **Third-Party Search Boundary:** Querying reverse-image engines requires network transmission. FaceProof treats this boundary as an explicit privacy hazard. The CLI and web interface refuse to dispatch search requests unless the user supplies an explicit `--consent-external-search` flag. If public image hosting is required to supply a URL to Google Lens, `--consent-public-upload` is also mandated.
* **Public Blockchain Boundary:** Public blockchains are permanent, immutable broadcast networks. Placing biometric templates, personal photographs, or plaintext URLs on a public ledger creates irreversible privacy and compliance violations. FaceProof anchors only two 32-byte cryptographic hashes:
  1. `bytes32 dataHash`: The SHA-256 digest of the canonicalized evidence record.
  2. `bytes32 urlHash`: The `keccak256` commitment of the matched candidate URL.

---

## 3. Computer Vision: Models and the Prominence Metric

FaceProof implements a pluggable vision architecture supporting two distinct runtime tiers:

### Permissive Default Engine (OpenCV YuNet + SFace)
For commercial and open-source compliance, FaceProof defaults to permissively licensed models:
* **Detection:** [YuNet](https://github.com/opencv/opencv_zoo/tree/master/models/face_detection_yunet) (MIT License), an ultra-lightweight (0.2 MB) convolutional detector designed for edge devices.
* **Recognition:** [SFace](https://github.com/opencv/opencv_zoo/tree/master/models/face_recognition_sface) (Apache-2.0 License), a MobileFaceNet backbone producing 128-dimensional spherical embeddings.
* **Execution:** Native OpenCV DNN module running on CPU.

### High-Accuracy Engine (SCRFD-10G + ArcFace R50 / R100)
For forensic and research applications requiring maximum discriminative power under severe pose or resolution degradation:
* **Detection:** SCRFD-10G, a multi-scale detector with five-point landmark localization and letterbox scaling.
* **Recognition:** ArcFace (ResNet-50 and ResNet-100 backbones) producing 512-dimensional embeddings via additive angular margin loss.
* **Execution:** ONNX Runtime with automatic CUDA acceleration when compatible GPUs are present.
* **Licensing Restriction:** The SCRFD and ArcFace pretrained weights from the InsightFace project are licensed strictly for **non-commercial research use only**. FaceProof embeds this license disclosure directly into every generated JSON record and prints a terminal warning whenever these engines are invoked.

### The Subject Selection Trap: Why "Largest Face" Fails
In photographic intake, an image frequently contains secondary faces: bystanders, background portraits, or group participants. Early prototypes followed the common convention of selecting the largest detected bounding box as the "subject."

When benchmarking this heuristic against the Labeled Faces in the Wild (LFW) dataset, we discovered that SCRFD detects multiple faces in 1,527 out of 7,701 raw images (~20%). In 2.4% of cases, an off-centre bystander or cropped background face had a marginally larger pixel area than the central subject. Relying on bounding-box area alone caused ArcFace-R50's accuracy to drop from **99.7% to 97.3%**.

To solve this, FaceProof implements a **prominence ranking metric**:

$$\text{Prominence} = \sqrt{\text{Area}} \times \left(1.0 - 0.5 \times \frac{d_{\text{centre}}}{d_{\text{max}}}\right)$$

where $d_{\text{centre}}$ is the Euclidean distance from the face centre to the image canvas centre, and $d_{\text{max}}$ is the diagonal half-distance. If a secondary face achieves a prominence score within 60% of the leader, FaceProof flags an ambiguity warning in the record, ensuring downstream reviewers know multiple subjects were present.

---

## 4. The Evidence Ladder: Face Matches vs. Image Derivatives

FaceProof enforces a strict separation between visual biometrics and image derivation:

* **Tier 1: Confirmed Face Match:** The query face and candidate face exhibit cosine similarity exceeding the engine's threshold (SFace $\ge 0.363$, ArcFace-R50 $\ge 0.25$). This captures human facial identity across different lighting, clothing, or dates.
* **Tier 2: Confirmed Image Derivative (Geometric Homography):** Evaluates whether the digital canvas was reused. Extracted SIFT features undergo Lowe's ratio test (0.75) and RANSAC homography estimation. If $\ge 25$ inliers agree on a non-degenerate perspective transform with an inlier ratio $\ge 0.30$, an image derivative is confirmed. This recovers crops, heavy rotations, and horizontal mirroring that hash algorithms miss.
* **Tier 3: Confirmed Image Derivative (Perceptual Hash):** Evaluates a 64-bit DCT perceptual hash. If Hamming distance is $\le 12$, an image derivative is confirmed.

Crucially, **an image derivative is never reported as a face match**. Conversely, if the same person appears in two entirely different photographs, geometric and perceptual hashes correctly report 0 inliers, but Tier 1 confirms a face match.

---

## 5. Network Security: Defeating SSRF and DNS Rebinding

Candidate URLs discovered via search engines are untrusted input. A malicious candidate URL could target `http://169.254.169.254/` (cloud metadata), `http://127.0.0.1:8765/` (loopback services), or trigger server-side request forgery (SSRF) via DNS rebinding.

FaceProof implements an isolated HTTP fetcher (`src/vision/netguard.py`) adhering to [OWASP SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) guidelines:

1. **Protocol and Port Pinning:** Only `http` and `https` schemes on destination ports `80` and `443` are allowed. Credentials in URLs (`user:pass@host`) are stripped.
2. **Socket-Level IP Pinning:** Standard libraries resolve hostnames via DNS and open a socket. In a DNS rebinding attack, the initial lookup returns a public IP, but the second lookup during TCP connection returns `127.0.0.1`. FaceProof resolves the IP first, validates that it does not belong to RFC 1918 (private), RFC 3927 (link-local), IPv6 loopback (`::1`), or NAT64 translation blocks, and **pins the socket connection directly to that validated IP address**.
3. **Manual Redirect Re-Validation:** Automated HTTP redirect following is disabled. Each HTTP 3xx redirect location is extracted, parsed, re-validated against IP blocklists, and counted toward a maximum budget of 3 hops.
4. **Memory and Dimension Guards:** Image responses are buffered to a 25 MiB cap. Image headers are parsed before full decompression; if dimensions exceed 16,384 pixels on a side or 50 megapixels in total area, the connection is terminated.

---

## 6. Cryptographic Sealing: Restricted RFC 8785 Canonical JSON

Once candidates have been evaluated, FaceProof seals the evidence into a canonical verification envelope (`schema: faceverify/v2`):

```json
{
  "schema": "faceverify/v2",
  "payload": {
    "schema": "faceverify/v2",
    "created_at": "2026-10-30T09:41:00Z",
    "evidence_type": "face_match",
    "source_image": {
      "filename": "query.png",
      "sha256": "4a7b...",
      "dimensions": [640, 480],
      "phash": "a1b2c3d4e5f60718"
    },
    "face": {
      "engine": "arcface-r50",
      "weights_sha256": "8c3f...",
      "embedding_commitment_sha256": "1e9a..."
    },
    "match": {
      "evidence_type": "face_match",
      "matched_url": "https://example.com/photo.jpg",
      "matched_url_commitment": "0x5d2a...",
      "face_cosine": "0.8942",
      "threshold": "0.2500"
    }
  },
  "integrity": {
    "algorithm": "sha256-jcs-rfc8785-restricted-v1",
    "verification_hash": "0x3f8a...",
    "canonical_length": 2418
  },
  "anchor": null
}
```

Hashing standard JSON across different programming languages is notoriously fragile. The Internet Engineering Task Force standardized JSON Canonicalization Scheme in [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785). FaceProof implements a **restricted profile** labelled `sha256-jcs-rfc8785-restricted-v1`:
* **Strict Integer Bounds:** Integers must fall within $[-(2^{53}-1), 2^{53}-1]$ (the safe IEEE 754 boundary where ES6 and Python integers perfectly agree).
* **Floats Forbidden in Hashes:** Floating-point numbers are prohibited in hashed payloads; scores are formatted as fixed-precision decimal strings (`"0.8942"`).
* **Deterministic UTF-16 Key Ordering:** Dictionary keys are sorted lexicographically by their UTF-16 code units.
* **Minimal String Escaping:** Formatted without whitespace, verified against test vectors published by the RFC Editor.

The resulting canonical byte array is hashed with SHA-256 to produce the `verification_hash`. Note that the `anchor` field is located **outside** the hashed payload. An on-chain transaction receipt cannot exist before the hash is computed; placing the transaction ID inside the hash would create an impossible circular dependency.

---

## 7. Blockchain Integration: EVM Registry v3 & Merkle Batches

FaceProof's smart contract (`contracts/VerificationRegistry.sol`) is written in Solidity 0.8.24 and targeted for the Base Sepolia Layer-2 testnet.

### Architectural Rules of the Registry

1. **First-Write-Wins:**
   ```solidity
   Record storage existing = _records[dataHash];
   if (existing.timestamp != 0) {
       revert AlreadyRegistered(dataHash, existing.timestamp, existing.submitter);
   }
   ```
   A naive registry allows any caller to overwrite an existing record. If Alice anchors a proof at timestamp $T_1$, an adversary could overwrite the record at $T_2$ to claim original discovery. FaceProof enforces first-write-wins: once a hash is registered, it can never be altered or overwritten by anyone, including the contract deployer.
2. **Zero Administration & No Upgrade Proxies:** The contract contains no owner address, no admin keys, no pause functions, and no proxy delegate calls. Its immutability is guaranteed by bytecode, not governance promises.
3. **Storage Slot Packing:** Record timestamps and block heights are constrained to `uint48`. This allows `address submitter` (20 bytes), `uint48 timestamp` (6 bytes), and `uint48 blockNumber` (6 bytes) to pack cleanly into a single 32-byte EVM storage slot, saving 20,000 gas per registration.

### URL Privacy via Commitments
In Registry v1, the contract took `string sourceUrl` as calldata. Even though the URL was stored as a hash, Ethereum calldata and event logs are permanently public.

In Registry v3, the client computes the commitment locally:

$$\text{urlHash} = \text{keccak256}(\text{UTF-8}(\text{URL}))$$

The smart contract receives only `register(bytes32 dataHash, bytes32 urlHash)`. The plaintext URL never reaches calldata, storage, or logs. When a third party inspects the record later, they supply their candidate URL; the client hashes it locally and calls `matchesUrlHash(dataHash, urlHash)`. *Note:* Commitments do not protect low-entropy or guessable URLs against dictionary brute-force search.

### Scalability: RFC 6962 Merkle-Batch Anchoring
Anchoring one transaction per image becomes cost-prohibitive in high-volume pipelines. Registry v3 introduces Merkle-batch registration based on Certificate Transparency ([RFC 6962](https://datatracker.ietf.org/doc/html/rfc6962)):

$$\text{Leaf}_i = \text{SHA-256}(0x00 \ || \ \text{dataHash}_i \ || \ \text{urlHash}_i)$$

$$\text{Parent} = \text{SHA-256}(0x01 \ || \ \text{Left} \ || \ \text{Right})$$

The registry exposes `registerBatch(bytes32 root, uint32 size)`. A single on-chain transaction anchors the root for thousands of records. Each individual record stores an off-chain inclusion proof of $\approx \lceil \log_2 N \rceil$ hashes. During independent verification, the verifier reconstructs the leaf from the record payload, checks the inclusion proof against the anchored root, and queries the blockchain for the root's timestamp.

---

## 8. Empirical Evaluation & Benchmarks

We measured FaceProof's components on real testbeds rather than theoretical estimates.

### Face Recognition Benchmarks (Public LFW Dataset)
The pipeline was benchmarked using the standard LFW 10-fold cross-validation protocol (6,000 pairs, 7,701 raw, unaligned images passed through full detection, alignment, and embedding):

| Metric / Engine | SFace (OpenCV, Apache-2.0) | ArcFace ResNet-50 (InsightFace) | ArcFace ResNet-100 (InsightFace) |
|---|---|---|---|
| **10-Fold Accuracy** | 99.32% ± 0.36 | **99.65% ± 0.29** | 99.63% ± 0.29 |
| **Equal Error Rate (EER)** | 0.83% | **0.60%** | 0.67% |
| **TAR @ FAR = 1e-3** | 98.47% | **99.33%** | 99.30% |
| **Threshold at FAR 1e-3** | 0.359 | 0.221 | 0.251 |
| **5× Downscale Stress** | 94.3% | **99.5%** | 99.3% |
| **30° Rotation Stress** | 90.2% | **99.7%** | 99.5% |
| **Latency (1280px canvas)** | 169 ms (Intel CPU) | **21 ms (NVIDIA RTX 4050)** | 26 ms (NVIDIA RTX 4050) |

*Evaluation Insights:*
1. **LFW is saturated.** Clean accuracy differences between R50 and R100 are within statistical noise. Under synthetic degradation (probes rotated by 30° or downscaled 5×), SFace drops by 5 to 9 percentage points, while ArcFace remains resilient (>99.3%).
2. **Threshold Sanity:** OpenCV's documented default threshold for SFace (0.363) aligns closely with our measured FAR = 1e-3 point (0.359), validating its operational default.

### Blockchain Gas Amortization
We measured transaction gas execution on an in-process EVM (Solidity 0.8.24, optimizer 200 runs):

| Operation | Total Gas | Gas per Record |
|---|---|---|
| **Single Record Registration (`register`)** | 74,464 gas | 74,464 gas |
| **Merkle Batch: $N = 1$ (`registerBatch`)** | 74,174 gas | 74,174 gas |
| **Merkle Batch: $N = 10$** | 74,174 gas | 7,417 gas |
| **Merkle Batch: $N = 1,000$** | 74,186 gas | **~74.2 gas** |

Merkle batches reduce gas costs per record by approximately **1,000×**, allowing intake workflows to anchor large evidence sets for negligible Layer-2 fees.

---

## 9. Engineering Challenges and Lessons Learned

1. **Failure Semantics vs. Negative Outcomes:** In early iterations, if a candidate URL timed out or a blockchain node failed to respond, the verifier returned `false` (indicating a failed verification). This conflated an infrastructure disruption with a tampered record. We introduced **exit code 6 (`inconclusive`)**. An unexecuted check is never presented as passed.
2. **Backward Compatibility in Cryptographic Formats:** Upgrading the canonicalizer to restrict integer ranges threatened to invalidate previously anchored records. We parameterized the verification engine: records declaring `sha256-jcs-rfc8785-restricted-v1` are evaluated under strict rules, while legacy records declaring `sha256-jcs-rfc8785` are verified under their original rules without re-interpretation.
3. **Testing Without Spending Real Funds:** Integrating blockchain tests into CI often tempts developers to mock Web3 clients. Mocking hides contract revert bugs and event encoding mismatches. We resolved this by integrating `eth-tester` with `py-evm`. CI compiles real Solidity bytecode with `solc 0.8.24` and executes full state transactions in an in-process virtual machine without connecting to a public network or spending testnet funds.

---

## 10. Current Status, Disclosures, and Limitations

To maintain uncompromising technical credibility, we explicitly disclose the project's current boundaries:

* **Smart Contract Deployment Status:** The `VerificationRegistry` v3 contract has been compiled and verified on an in-process EVM. **It has not been deployed to the public Base Sepolia testnet.** Deployment remains a deliberate, manual operation.
* **Hosting Architecture:** FaceProof's web interface is local-first (`127.0.0.1:8765`). It contains **no authentication layer** and must never be exposed to public networks. The public showcase website on GitHub Pages is a static overview and architecture explorer; it does not host a live multi-user verification server.
* **Evaluation Scope:** Face recognition benchmarks were conducted exclusively on LFW. Performance on IJB-C, CFP-FP, AgeDB, and demographic subsets was not measured. **No fairness or demographic parity claim is made.**
* **Model Licensing:** The permissive OpenCV Zoo models (YuNet/SFace) are Apache-2.0 / MIT. The high-accuracy ArcFace and SCRFD weights are strictly restricted to **non-commercial research use**.
* **Repository Licensing:** While the smart contract carries an MIT SPDX header, the root repository currently lacks an overarching LICENSE file. Third-party components operate under their respective licenses.

---

## 11. Conclusion

True image provenance cannot rely on ephemeral search engine queries or easily forged browser screenshots. A credible provenance architecture must preserve not only what conclusion was reached, but also the full chain of custody: the raw leads discovered, the exact network boundary traversed, the biometric and geometric algorithms applied, and the cryptographic commitments anchored in time.

By coupling local-first computer vision with deterministic canonicalization and immutable blockchain commitments, FaceProof provides an evidence-first foundation for digital provenance—open, inspectable, and honestly bounded.

---

### Technical References

1. **RFC 8785 (JSON Canonicalization Scheme - JCS):** Rundgren, A., Jordan, M., & Erdtman, S. (2020). *RFC 8785: JSON Canonicalization Scheme*. IETF. [https://www.rfc-editor.org/rfc/rfc8785](https://www.rfc-editor.org/rfc/rfc8785)
2. **RFC 6962 (Certificate Transparency):** Laurie, B., Langley, A., & Kasper, E. (2013). *RFC 6962: Certificate Transparency*. IETF. [https://datatracker.ietf.org/doc/html/rfc6962](https://datatracker.ietf.org/doc/html/rfc6962)
3. **OpenCV Zoo Models:** OpenCV Team. (2023). *YuNet & SFace ONNX Models*. [https://github.com/opencv/opencv_zoo](https://github.com/opencv/opencv_zoo)
4. **ArcFace:** Deng, J., Guo, J., Xue, N., & Zafeiriou, S. (2019). *ArcFace: Additive Angular Margin Loss for Deep Face Recognition*. IEEE CVPR. [https://doi.org/10.1109/CVPR.2019.00482](https://doi.org/10.1109/CVPR.2019.00482)
5. **C2PA Technical Specifications:** Coalition for Content Provenance and Authenticity. (2023). *C2PA Technical Specification v1.3*. [https://c2pa.org/specifications/specifications/1.3/index.html](https://c2pa.org/specifications/specifications/1.3/index.html)
6. **OWASP SSRF Prevention Cheat Sheet:** OWASP Foundation. (2024). *Server-Side Request Forgery Prevention*. [https://cheatsheetseries.owasp.org/](https://cheatsheetseries.owasp.org/)
7. **Base Layer-2 Documentation:** Base Engineering Team. (2024). *Base Developer Documentation*. [https://docs.base.org/](https://docs.base.org/)
8. **Web3.py Documentation:** Ethereum Foundation. (2024). *Web3.py v7 Documentation*. [https://web3py.readthedocs.io/](https://web3py.readthedocs.io/)
