## 🖥️ FaceProof — Web Application Vision
**FaceProof** is a proposed web interface for the Face Blockchain Verification project, designed to transform an existing Python-based image provenance verification pipeline into an interactive, evidence-driven application.

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
