## 🖥️ FaceProof — Web Application Vision
**FaceProof** is a web interface (first local slice implemented; see Development Status) for the Face Blockchain Verification project, designed to transform an existing Python-based image provenance verification pipeline into an interactive, evidence-driven application.

The goal is to make image provenance analysis, candidate comparison, cryptographic integrity checks, and blockchain-backed verification accessible through a clean, modern interface.

### 🎯 Product Vision

Instead of interacting with the verification engine through terminal commands, users will be able to upload an image, follow the verification process, inspect candidate matches, and retrieve a cryptographically verifiable evidence receipt through a web application.

### ✨ Planned Features

- **Interactive Image Upload** — Upload and preview images before initiating a verification run.
- **Live Verification Pipeline** — Track face detection, reverse-image search, candidate confirmation, and blockchain anchoring.
- **Candidate Comparison** — Inspect the source image alongside candidate images, similarity scores, perceptual-hash distances, and source URLs.
- **Blockchain Proof Receipts** — View verification hashes, transaction hashes, block numbers, timestamps, and blockchain explorer links.
- **Evidence Case Management** — Review verification runs, inspect evidence artifacts, and download verification records.
- **Independent Record Verification** — Upload an existing verification record and check its integrity against the original image and on-chain data.
- **System Health Monitoring** — Inspect model availability, search-provider connectivity, RPC connectivity, and contract configuration.
- **Transparent Failure Handling** — Clearly distinguish unsuccessful searches, rejected candidates, integrity mismatches, network errors, and successful verification.

### 🧩 Proposed Application Architecture

```text
┌───────────────────────────────────────────┐
│          React + TypeScript UI            │
│                                           │
│ Dashboard · Upload · Results · Evidence   │
│             Proof Receipts                │
└─────────────────────┬─────────────────────┘
                      │ REST API
┌─────────────────────▼─────────────────────┐
│              FastAPI Backend              │
│                                           │
│ Validation · Job Status · File Handling   │
│         Results · Evidence Access         │
└─────────────────────┬─────────────────────┘
                      │
┌─────────────────────▼─────────────────────┐
│         Existing Python Engine            │
│                                           │
│ OpenCV · Reverse Image Search              │
│ Candidate Matching · SHA-256 Integrity    │
│          Evidence Generation              │
└─────────────────────┬─────────────────────┘
                      │
           ┌──────────┴──────────┐
           ▼                     ▼
┌───────────────────┐  ┌────────────────────┐
│ Evidence Storage  │  │ Blockchain Registry│
│                   │  │                    │
│ JSON · Images     │  │ Verification Hash  │
│ Manifest · Reports│  │ Base Sepolia       │
└───────────────────┘  └────────────────────┘
```

### 🛠️ Proposed Frontend Stack

| Component | Technology |
|---|---|
| Frontend | React + TypeScript + Vite |
| UI and styling | Tailwind CSS + shadcn/ui *(proposed; the implemented UI uses plain CSS)* |
| Icons | Lucide *(proposed; not used)* |
| Backend API | FastAPI |
| Computer vision | Existing OpenCV-based pipeline |
| Blockchain integration | Existing Web3.py client and Solidity registry |
| Evidence format | JSON verification records and SHA-256 manifests |

### 🔄 Intended User Workflow

1. Upload an image and review the privacy implications.
2. Run face detection and reverse-image search.
3. Inspect candidate webpages and independent face-match results.
4. Review the verification outcome and supporting evidence.
5. Anchor a confirmed verification record on the configured blockchain.
6. View the proof receipt, inspect the evidence bundle, or export the record.
7. Independently verify a saved record at a later time.

### 🔐 Security, Privacy & Verification

FaceProof is designed around transparency and verifiable evidence.

- Verification hashes are computed from canonicalized records.
- The smart contract stores cryptographic commitments rather than face embeddings or image files.
- Local integrity checks detect modifications to saved verification records.
- Blockchain lookups establish whether the corresponding hash was registered and whether the source URL commitment agrees with the record.
- Image uploads and third-party search services must be handled with explicit user consent and appropriate data-retention controls.
- Testnet transactions and simulated blockchain results must be clearly distinguished from actual on-chain transactions.

**Important limitation:** A matching face or image does not establish a person's legal identity, prove ownership of an image, or establish that a webpage is authentic. Blockchain anchoring proves that a particular cryptographic commitment was registered; it does not independently prove the underlying claim is true.

### 🚧 Development Status

*Updated against the code, 2026-10-29.* A **first local vertical slice is implemented and tested**; the rest of
this document is still vision.

**Implemented** (`src/web/`, `web/`; see the README "Local web app" section):

- Upload with preview, a privacy/consent panel, and a real pipeline job with honest stage status (no fake
  percentages).
- Candidate table, face-match vs image-derivative labelling, comparison image, claim and limitations.
- Download of the real record and evidence manifest; independent record verification with optional image
  binding; per-check PASS / FAIL / COULD NOT RUN / NOT CHECKED results; simulated chain and test-only
  labelling.
- Loopback-only server, upload limits, temp-file cleanup, no secrets or stack traces in responses.
- Verified by 23 API tests running the real pipeline in demo mode, and one manual browser run. There are
  **no automated browser tests**.

**Not implemented:** Tailwind CSS / shadcn/ui / Lucide (the UI uses plain CSS; the table above is the original
proposal, not what was built); persistent "evidence case management" (jobs live in a temporary directory and
expire after an hour; the CLI's `evidence/` folder is the durable record); a system-health dashboard beyond the
`/api/health` flags; a separate "review, then anchor" step (the run registers automatically unless the
simulated chain is used); real-chain registration from the UI is off unless the server is started with
`--allow-chain-writes`.

---

**Project direction:** Turn a working command-line verification engine into a user-friendly, auditable image provenance platform with transparent results and independently checkable blockchain evidence.
