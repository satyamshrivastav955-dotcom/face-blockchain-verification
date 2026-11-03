# FaceProof Public Release & Launch Checklist

This checklist defines the complete release readiness criteria for **FaceProof v2.0.0**. Every check must be evaluated and marked by the release manager prior to external publication.

---

## 1. Technical Pre-Deployment Verification

- [x] **Python Code Compilation**:
  `python -m compileall -q src tests scripts` exits with code `0`.
- [x] **Hermetic Test Suite**:
  `python -m pytest tests -q -ra` passes (658 passed, 8 skipped for optional uninstalled weights/EVM).
- [x] **CLI Smoke Test**:
  `python -m src.main --help` displays clean usage instructions and correct subcommands.
- [x] **Environment Diagnostics**:
  `python -m src.main doctor --offline` reports verified models and dependency health with zero secret leakage.
- [x] **Local Web Frontend Build**:
  `cd web && npm ci && npm run build` compiles clean Vite assets with zero errors.
- [x] **Static Showcase Build**:
  `cd showcase && npm ci && npm run build` compiles clean static assets to `showcase/dist` with zero errors.
- [x] **CI Matrix Investigation**:
  Resolved Python 3.11 dependency compatibility in `constraints.txt` (pinned `numpy==2.2.6`).

---

## 2. Public Static Showcase Deployment (GitHub Pages)

- [x] **Independent Architecture**: `showcase/` is completely decoupled from the local FastAPI server.
- [x] **Zero Live API Calls**: Verified that `showcase/dist` makes no HTTP requests to `/api/*`.
- [x] **Asset Paths & Routing**: Configured relative base path `./` and base `/face-blockchain-verification/`.
- [x] **Custom 404 Page**: Verified `showcase/public/404.html` exists and adheres to brand aesthetics.
- [x] **GitHub Actions Workflow**: `.github/workflows/deploy-showcase.yml` uses official `upload-pages-artifact@v3` and `deploy-pages@v4`.
- [ ] **Manual Activation in GitHub Settings** *(Action required by maintainer)*:
  1. Open GitHub repo &rarr; **Settings** &rarr; **Pages**.
  2. Set **Build and deployment > Source** to **GitHub Actions**.
- [ ] **Trigger Showcase Deployment** *(Action required by maintainer)*:
  Execute manual trigger via **Actions &rarr; Deploy Showcase to GitHub Pages &rarr; Run workflow**.
- [ ] **Post-Deploy Live URL Verification**:
  Verify `https://satyamshrivastav955-dotcom.github.io/face-blockchain-verification/`.

---

## 3. Visual Assets & Privacy Review

- [x] **Automated Screenshot Integrity**: All visual assets in `assets/readme/` are captured via `scripts/capture_screenshots.py` using synthetic fixtures.
- [x] **Mandatory Demo Disclaimers**: UI demo GIF explicitly labelled:
  *"Offline demonstration — synthetic fixture, stub recognition engine and simulated blockchain."*
- [x] **Third-Party Photograph Review**: Historical screenshots (`assets/demo_confirmed_match.png` and `assets/demo_rejected_claim.png`) containing third-party photographs have been excluded from public release documentation and showcase pages.
- [x] **SVG Diagram Re-generation**: `assets/readme/` diagrams generated via `scripts/make_readme_assets.py`.

---

## 4. Smart Contract Deployment Readiness (Base Sepolia)

- [x] **Source Invariants**: Confirmed first-write-wins guard, zero-hash validation, and zero admin backdoors in `contracts/VerificationRegistry.sol`.
- [x] **Compiler & Target**: Solidity `0.8.24`, optimizer `runs: 200`, Cancun EVM target.
- [x] **Interface Version**: Confirmed `registryVersion() == 3` (Merkle-batch support).
- [x] **Clean Deployment Guide**: Created `docs/BASE_SEPOLIA_RELEASE.md` with step-by-step instructions.
- [x] **Burner Wallet Policy**: Enforced burner-only policy; zero real/mainnet private keys in repository.
- [x] **Deployment Status Transparency**: Disclosed that contract is compiled and tested on in-process EVM, but **not yet deployed on live Base Sepolia testnet**.
- [ ] **Contract Testnet Deployment** *(Action required by maintainer)*:
  Execute `python -m src.main deploy --yes --save` using funded Base Sepolia burner wallet.
- [ ] **Contract Source Verification on BaseScan** *(Action required by maintainer)*:
  Verify flattened source on BaseScan Sepolia.

---

## 5. Security & Privacy Audit

- [x] **Zero Secret Leakage**: Verified `.env` is git-ignored and no API keys or private keys exist in tracked files.
- [x] **Local-First Boundary**: Verified FastAPI app binds only to `127.0.0.1` and enforces Host/Origin validation.
- [x] **SSRF Protection**: Verified IP-pinning, redirect re-validation, and dimension/size caps in `src/vision/netguard.py`.
- [x] **Consent Enforcement**: Verified CLI and API refuse search/upload operations without explicit `--consent-*` flags.
- [x] **Biometric Commitment Handling**: Verified face embeddings are never persisted or anchored on-chain.

---

## 6. Technical Publication & Developer Relations

- [x] **Technical Article Drafted**: Comprehensive engineering case study in `docs/articles/faceproof-engineering-story.md` (~3,100 words including diagrams, citations, and schemas).
- [x] **Authoritative References**: Directly linked RFC 8785, RFC 6962, OpenCV, ArcFace, C2PA, Base, Web3.py.
- [x] **LinkedIn Launch Announcement**: Drafted in `docs/articles/linkedin-launch-announcement.md`.
- [x] **Release Notes Prepared**: Documented in `docs/RELEASE_NOTES.md`.
- [ ] **Publish Article on Technical Platforms** *(Action required by maintainer)*:
  Cross-post to Dev.to, Medium, or Hashnode with canonical URL pointing to repository.
- [ ] **Post LinkedIn Announcement** *(Action required by maintainer)*:
  Share update on LinkedIn with repository and showcase links.

---

## 7. Post-Launch Verification

- [ ] Confirm showcase loads over HTTPS on GitHub Pages.
- [ ] Confirm all repository documentation links resolve correctly.
- [ ] Monitor initial issue submissions via GitHub Private Vulnerability Reporting.
