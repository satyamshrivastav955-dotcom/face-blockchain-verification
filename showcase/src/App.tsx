import { useState } from "react";

export default function App() {
  const [activeTab, setActiveTab] = useState<"overview" | "local" | "providers" | "blockchain">("overview");
  const [selectedEngine, setSelectedEngine] = useState<"sface" | "r50" | "r100">("r50");

  return (
    <div className="site-wrapper">
      {/* Top Navigation */}
      <header className="site-header">
        <div className="container nav-row">
          <div className="brand-group">
            <span className="brand-stamp">EVIDENCE RECORD</span>
            <span className="brand-title">FaceProof</span>
          </div>
          <nav className="nav-links">
            <a href="#introduction" className="nav-link">Motivation</a>
            <a href="#architecture" className="nav-link">Architecture</a>
            <a href="#capabilities" className="nav-link">Capabilities</a>
            <a href="#gallery" className="nav-link">Product Tour</a>
            <a href="#evidence-trust" className="nav-link">Evidence Ladder</a>
            <a href="#evaluation" className="nav-link">Evaluation</a>
            <a href="#reproducibility" className="nav-link">Run Locally</a>
          </nav>
          <div>
            <a
              href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification"
              target="_blank"
              rel="noopener noreferrer"
              className="nav-button"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
              </svg>
              GitHub Repository
            </a>
          </div>
        </div>
      </header>

      {/* 1. Hero Section */}
      <section className="hero">
        <div className="container">
          <div className="hero-pill">
            <span className="hero-pill-dot"></span>
            <span>SPECIFICATION v2.0.0 &middot; REGISTRY INTERFACE v3 &middot; RELEASE CANDIDATE</span>
          </div>
          <h1 className="hero-headline serif">
            Every image has a history.<br />Give its evidence a record.
          </h1>
          <p className="hero-subtitle">
            An evidence-first image provenance system combining local computer vision, reverse-image search, cryptographic integrity, and blockchain anchoring.
          </p>

          <div className="hero-actions">
            <a
              href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary"
            >
              View Source on GitHub
            </a>
            <a href="#architecture" className="btn-secondary">
              Explore Architecture
            </a>
            <a href="#reproducibility" className="btn-secondary mono">
              $ python -m src.main doctor
            </a>
          </div>

          {/* Three Key Pillars */}
          <div className="hero-pillars">
            <div className="pillar-card">
              <h3 className="pillar-title serif">
                <span className="badge badge-oxblood">HONEST</span>
                Evidence, Not Assertions
              </h3>
              <p className="pillar-desc">
                Every candidate is explicitly classified as a <em>face match</em> or <em>image derivative</em>. Image similarity is never inflated into biometric identity, and checks that cannot run fail <em>inconclusive</em>, never as a pass.
              </p>
            </div>

            <div className="pillar-card">
              <h3 className="pillar-title serif">
                <span className="badge badge-sage">LOCAL-FIRST</span>
                Zero-Leak Biometrics
              </h3>
              <p className="pillar-desc">
                Detection, alignment, embedding, candidate re-examination, and canonical hashing run 100% on your machine. Biometric embeddings are never stored on disk or written to the blockchain.
              </p>
            </div>

            <div className="pillar-card">
              <h3 className="pillar-title serif">
                <span className="badge badge-navy">ANCHORED</span>
                Tamper-Evident Receipts
              </h3>
              <p className="pillar-desc">
                Verification payloads are sealed with deterministic RFC 8785 canonical JSON and SHA-256. Anchored on an EVM registry using first-write-wins commitments or gas-amortized Merkle batches.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 2. Project Introduction */}
      <section id="introduction" className="section">
        <div className="container">
          <div className="section-head">
            <span className="section-tag">01 / MOTIVATION</span>
            <h2 className="section-title serif">Beyond the Ephemeral Search Result</h2>
            <p className="section-desc">
              Images circulate across websites, social media, forums, and syndication platforms. Today, understanding where an image appears and whether a candidate image is visually related requires more than simply trusting a search engine query.
            </p>
          </div>

          <div className="grid-2">
            <div className="card">
              <span className="card-tag">THE PROBLEM</span>
              <h3 className="card-title serif">Search Hits Are Leads, Not Evidence</h3>
              <p className="card-desc">
                When an investigator or engineer performs a reverse-image search, the provider returns raw links. Those URLs change, pages get deleted, and algorithms hallucinate unrelated matches. A browser screenshot provides no verifiable proof of what was examined, what image resolution was downloaded, or which facial landmarks agreed.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">THE APPROACH</span>
              <h3 className="card-title serif">Independent Re-Examination &amp; Sealing</h3>
              <p className="card-desc">
                FaceProof treats search hits strictly as leads. The engine downloads each candidate under strict SSRF protections, performs independent local biometric and geometric re-examination, evaluates C2PA Content Credentials, and seals the entire finding into an immutable, verifiable cryptographic record.
              </p>
            </div>
          </div>

          <div className="notice-box">
            <h4 className="notice-title">Important Semantic Boundary</h4>
            <p className="notice-text">
              FaceProof is an <strong>image-provenance tool, not an identity-recognition product</strong>. It never maps a face to a person or proves legal identity. A blockchain commitment establishes that a particular record hash was anchored at a specific block timestamp; it does not prove that an external claim is true or that a webpage is authentic.
            </p>
          </div>
        </div>
      </section>

      {/* 3. System Architecture */}
      <section id="architecture" className="section" style={{ background: "var(--bg-secondary)" }}>
        <div className="container">
          <div className="section-head">
            <span className="section-tag">02 / ARCHITECTURE</span>
            <h2 className="section-title serif">Operational Boundaries &amp; Data Flow</h2>
            <p className="section-desc">
              Every operation runs within an explicit trust boundary. Biometric data never leaves the local machine, external services require explicit user consent, and the public blockchain receives only cryptographic hashes.
            </p>
          </div>

          {/* Interactive Trust Boundary Selector */}
          <div style={{ display: "flex", gap: "8px", marginBottom: "20px" }}>
            <button
              onClick={() => setActiveTab("overview")}
              className={`nav-button ${activeTab === "overview" ? "badge-navy" : ""}`}
              style={{ cursor: "pointer", fontWeight: activeTab === "overview" ? 600 : 400 }}
            >
              Full Architecture
            </button>
            <button
              onClick={() => setActiveTab("local")}
              className={`nav-button ${activeTab === "local" ? "badge-sage" : ""}`}
              style={{ cursor: "pointer", fontWeight: activeTab === "local" ? 600 : 400 }}
            >
              Local Workstation Focus
            </button>
            <button
              onClick={() => setActiveTab("providers")}
              className={`nav-button ${activeTab === "providers" ? "badge-ochre" : ""}`}
              style={{ cursor: "pointer", fontWeight: activeTab === "providers" ? 600 : 400 }}
            >
              Search &amp; SSRF Bounds
            </button>
            <button
              onClick={() => setActiveTab("blockchain")}
              className={`nav-button ${activeTab === "blockchain" ? "badge-oxblood" : ""}`}
              style={{ cursor: "pointer", fontWeight: activeTab === "blockchain" ? 600 : 400 }}
            >
              Blockchain Registry
            </button>
          </div>

          {/* Architecture Visual */}
          <div style={{ textAlign: "center", marginBottom: "32px" }}>
            <img
              src="./assets/pipeline.svg"
              alt="FaceProof Pipeline Architecture"
              style={{ maxWidth: "100%", height: "auto", border: "1px solid var(--rule-base)", background: "#faf6ea", borderRadius: "3px" }}
            />
          </div>

          {activeTab === "local" && (
            <div className="notice-box" style={{ borderLeftColor: "var(--accent-sage)" }}>
              <h4 className="notice-title">Local Processing Boundary</h4>
              <p className="notice-text">
                All facial detection (YuNet / SCRFD), landmark alignment (Umeyama similarity transform), and feature extraction (SFace / ArcFace) take place exclusively in local RAM. Biometric vectors are evaluated in ephemeral memory and discarded immediately after similarity scoring.
              </p>
            </div>
          )}

          {activeTab === "providers" && (
            <div className="notice-box" style={{ borderLeftColor: "var(--accent-ochre)" }}>
              <h4 className="notice-title">Guarded Provider Boundary</h4>
              <p className="notice-text">
                Candidate URLs are untrusted user input. FaceProof resolves IP addresses before connecting, blocks loopback/RFC 1918/link-local ranges, pins TCP sockets directly to the verified IP, and enforces strict HTTP limits (&le; 25 MiB, &le; 16,384 px per side).
              </p>
            </div>
          )}

          {activeTab === "blockchain" && (
            <div className="notice-box" style={{ borderLeftColor: "var(--accent-oxblood)" }}>
              <h4 className="notice-title">Public Blockchain Boundary</h4>
              <p className="notice-text">
                The smart contract receives exactly two 32-byte values: <code>dataHash</code> (SHA-256 of canonical payload) and <code>urlHash</code> (Keccak-256 of candidate URL). No personal data or plaintext links are ever submitted or logged in EVM events.
              </p>
            </div>
          )}

          {/* Operational Boundaries Table */}
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Processing Domain</th>
                  <th>Operations Executed</th>
                  <th>Data Handled</th>
                  <th>Privacy &amp; Security Boundary</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>Local Workstation</strong></td>
                  <td>Face detection, 5-pt alignment, embedding, pHash, SIFT+RANSAC homography, canonical JSON sealing, SHA-256</td>
                  <td>Input image, cropped face tensors, 128-d / 512-d feature vectors, candidate image downloads</td>
                  <td><span className="badge badge-sage">STRICTLY LOCAL</span> No embeddings or raw pixels stored or transmitted</td>
                </tr>
                <tr>
                  <td><strong>Third-Party Providers</strong></td>
                  <td>Reverse-image search (Google Lens via SerpApi, TinEye API), optional image hosting</td>
                  <td>Query image hash / query URL (or image upload with affirmative consent)</td>
                  <td><span className="badge badge-ochre">EXPLICIT CONSENT</span> Requires <code>--consent-external-search</code></td>
                </tr>
                <tr>
                  <td><strong>Public Blockchain</strong></td>
                  <td>First-write-wins registry anchor, Merkle-root batch registration, existence check</td>
                  <td><code>bytes32 dataHash</code> (SHA-256), <code>bytes32 urlHash</code> (Keccak-256), Merkle roots</td>
                  <td><span className="badge badge-navy">PSEUDONYMOUS COMMITMENTS</span> No plaintext URLs, no personal data, no embeddings</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* 4. Technical Capabilities */}
      <section id="capabilities" className="section">
        <div className="container">
          <div className="section-head">
            <span className="section-tag">03 / IMPLEMENTED FEATURES</span>
            <h2 className="section-title serif">Engineered for Technical Rigour</h2>
            <p className="section-desc">
              Every capability is backed by tested source code and verified invariants in the repository.
            </p>
          </div>

          <div className="grid-3">
            <div className="card">
              <span className="card-tag">COMPUTER VISION</span>
              <h3 className="card-title serif">Dual-Engine Face Pipeline</h3>
              <p className="card-desc">
                Default permissive engine uses OpenCV YuNet (detection) and SFace (128-d embeddings). Optional high-accuracy engine utilizes SCRFD-10G and ArcFace (ResNet-50/100, 512-d) via ONNX Runtime with CUDA acceleration.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">BIOMETRICS</span>
              <h3 className="card-title serif">Prominence Face Selection</h3>
              <p className="card-desc">
                Ranks candidate faces using <code>sqrt(area) &times; centrality</code>. Benchmarked against LFW: avoids the 2.4-percentage-point accuracy loss caused by naive "largest face" heuristics.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">NETWORK SECURITY</span>
              <h3 className="card-title serif">SSRF-Guarded Fetcher</h3>
              <p className="card-desc">
                Candidate downloads pin TCP sockets to validated IPs to defeat DNS rebinding. Redirects are manually inspected, internal/private IP ranges blocked, and limits enforced (&le; 16,384 px, &le; 50 MP, &le; 25 MiB).
              </p>
            </div>

            <div className="card">
              <span className="card-tag">EVIDENCE INTEGRITY</span>
              <h3 className="card-title serif">Restricted RFC 8785 JSON</h3>
              <p className="card-desc">
                Canonicalizes verification payloads deterministically (JCS profile <code>sha256-jcs-rfc8785-restricted-v1</code>). Enforces integer bounds, forbids floats in hashed sections, and cross-checks with JavaScript engines.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">SOLIDITY REGISTRY</span>
              <h3 className="card-title serif">First-Write-Wins Registry</h3>
              <p className="card-desc">
                EVM smart contract (Solidity 0.8.24) deployed on Base Sepolia. Immutable design with zero administrative backdoors, zero upgrade keys, and packed <code>uint48</code> storage slots saving 20k gas.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">SCALABILITY</span>
              <h3 className="card-title serif">RFC 6962 Merkle Batches</h3>
              <p className="card-desc">
                Anchors up to 1,000 records in a single on-chain transaction. Amortizes gas cost down to approximately ~74 gas per record while generating individual logarithmic inclusion proofs.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">PROVENANCE STANDARDS</span>
              <h3 className="card-title serif">C2PA Manifest Inspection</h3>
              <p className="card-desc">
                Reads Content Credentials on source and candidate images via <code>c2pa-python</code>. Evaluates cryptographic signatures and reports declarations of AI generation or camera provenance independently.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">PRIVACY COMMITMENT</span>
              <h3 className="card-title serif">Keccak-256 URL Commitments</h3>
              <p className="card-desc">
                The registry never accepts or logs plaintext URLs. Clients submit <code>keccak256(bytes(url))</code>, allowing zero-knowledge verification by parties already in possession of the candidate URL.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">EVIDENCE RETENTION</span>
              <h3 className="card-title serif">Verifiable Case Manifests</h3>
              <p className="card-desc">
                Every verification run produces an evidence bundle directory containing the raw API response, candidate table, and image digests bound to the sealed record by SHA-256 manifest.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 5. Product Screenshots & Tour */}
      <section id="gallery" className="section" style={{ background: "var(--bg-secondary)" }}>
        <div className="container">
          <div className="section-head">
            <span className="section-tag">04 / APPLICATION WALKTHROUGH</span>
            <h2 className="section-title serif">Verified Product Screenshots</h2>
            <p className="section-desc">
              All visual assets below are genuine captures of the real running application generated via automated UI harness.
            </p>
          </div>

          <div className="gallery-grid">
            <div className="gallery-card">
              <div className="gallery-media">
                <img src="./assets/landing_hero.png" alt="FaceProof Case Intake Interface" />
              </div>
              <div className="gallery-caption">
                <strong>Workspace Intake &amp; Case Initiation</strong>
                Clean, local-first interface for loading query images, configuring search parameters, and selecting verification engines.
              </div>
            </div>

            <div className="gallery-card">
              <div className="gallery-media">
                <img src="./assets/workspace_intake.png" alt="Privacy disclosure and consent modal" />
              </div>
              <div className="gallery-caption">
                <strong>Mandatory Disclosure &amp; Consent Notice</strong>
                The intake view displays exactly what information will leave the workstation before any external API request is dispatched.
              </div>
            </div>

            <div className="gallery-card">
              <div className="gallery-media">
                <img src="./assets/examination.png" alt="Six-step record verification view" />
              </div>
              <div className="gallery-caption">
                <strong>Six-Stage Record Examination</strong>
                Independent examination checking canonical hash integrity, image binding, evidence bundle digests, and blockchain anchor status.
              </div>
            </div>

            <div className="gallery-card">
              <div className="gallery-media">
                <img src="./assets/workspace_result.png" alt="Finished case proceedings and candidate schedule" />
              </div>
              <div className="gallery-caption">
                <strong>Completed Case Proceedings &amp; Findings</strong>
                Schedule of candidate leads preserving rejected items alongside verified matches, metric scores, and seal metadata.
              </div>
            </div>
          </div>

          {/* Animated Demonstration with Mandatory Disclaimer */}
          <div style={{ marginTop: "40px" }} className="gallery-card">
            <div className="gallery-media">
              <img src="./assets/demo.gif" alt="Full verification lifecycle demonstration" />
            </div>
            <div className="gallery-caption">
              <strong>Complete Lifecycle Recording (Intake &rarr; Examine &rarr; Seal &rarr; Verify)</strong>
              <div style={{ marginTop: "6px", color: "var(--accent-oxblood)", fontWeight: 600, fontFamily: "var(--font-mono)", fontSize: "12px" }}>
                OFFLINE DEMONSTRATION &mdash; SYNTHETIC FIXTURE, STUB RECOGNITION ENGINE AND SIMULATED BLOCKCHAIN.
              </div>
              <p style={{ marginTop: "4px", fontSize: "13px" }}>
                Notice: Historical screenshots from earlier builds (which contained third-party photographs and deprecated contract v1 interfaces) have been permanently retired from public release materials in accordance with our privacy policy.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 6. Evidence and Trust */}
      <section id="evidence-trust" className="section">
        <div className="container">
          <div className="section-head">
            <span className="section-tag">05 / EVIDENCE LADDER</span>
            <h2 className="section-title serif">Honest Evidence Classification</h2>
            <p className="section-desc">
              FaceProof enforces strict semantic boundaries between biometric identity, geometric transforms, and perceptual image derivatives.
            </p>
          </div>

          <div style={{ textAlign: "center", marginBottom: "36px" }}>
            <img
              src="./assets/evidence_ladder.svg"
              alt="FaceProof Evidence Ladder Diagram"
              style={{ maxWidth: "100%", height: "auto", border: "1px solid var(--rule-base)", background: "#faf6ea", borderRadius: "3px" }}
            />
          </div>

          <div className="grid-2">
            <div className="card">
              <span className="card-tag">BIOMETRIC SIMILARITY</span>
              <h3 className="card-title serif">Confirmed Face Match</h3>
              <p className="card-desc">
                Requires the facial embedding cosine similarity between the query face and a detected face in the candidate image to exceed the engine threshold (SFace &ge; 0.363, ArcFace R50 &ge; 0.25). Captures facial identity regardless of different background, clothing, or pose.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">IMAGE RE-USE &amp; CROPS</span>
              <h3 className="card-title serif">Confirmed Image Derivative</h3>
              <p className="card-desc">
                Derived from either <strong>SIFT + RANSAC geometric verification</strong> (&ge; 25 inliers, non-degenerate homography recovering crops and rotations) or <strong>64-bit DCT perceptual hashing</strong> (pHash distance &le; 12). Proves visual image derivation, <em>never</em> biometric identity.
              </p>
            </div>
          </div>

          <div className="notice-box">
            <h4 className="notice-title">Exit Code 6: Inconclusive Means Inconclusive</h4>
            <p className="notice-text">
              In FaceProof, if an RPC node is unreachable, a contract version is incompatible, or an external provider fails, the system returns exit code <strong>6 (Inconclusive)</strong>. An unexecuted check is never marked as passed.
            </p>
          </div>
        </div>
      </section>

      {/* 7. Privacy and Security Posture */}
      <section id="privacy" className="section" style={{ background: "var(--bg-secondary)" }}>
        <div className="container">
          <div className="section-head">
            <span className="section-tag">06 / SECURITY &amp; PRIVACY</span>
            <h2 className="section-title serif">Privacy-Preserving Provenance</h2>
            <p className="section-desc">
              Engineered with a defensive threat model to prevent biometric leakage, protect internal networks, and maintain verifiable records.
            </p>
          </div>

          <div className="grid-3">
            <div className="card">
              <span className="card-tag">LOCAL EMBEDDINGS</span>
              <h3 className="card-title serif">No Vectors on the Ledger</h3>
              <p className="card-desc">
                Neither raw 512-d embeddings nor compressed biometric vectors are written to the blockchain. The record contains only an <code>embedding_commitment_sha256</code> to prove possession without publishing biometric data.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">INFRASTRUCTURE DEFENSE</span>
              <h3 className="card-title serif">Host &amp; Origin Pinning</h3>
              <p className="card-desc">
                The local web backend binds exclusively to loopback (<code>127.0.0.1</code>), enforces strict Host and Origin validation, and provides no authentication. It is explicitly designed not to be exposed to public networks.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">URL PRIVACY LIMITS</span>
              <h3 className="card-title serif">Honest Brute-Force Limits</h3>
              <p className="card-desc">
                The registry stores <code>keccak256(url)</code>. While this prevents casual discovery on block explorers, commitments are not secret against targeted guessing of predictable or known URLs.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 8. Reproducibility & Quickstart */}
      <section id="reproducibility" className="section">
        <div className="container">
          <div className="section-head">
            <span className="section-tag">07 / QUICKSTART</span>
            <h2 className="section-title serif">Reproducibility &amp; Local Execution</h2>
            <p className="section-desc">
              Every command below is tested and reproducible. Verify the environment on your machine with pinned dependencies.
            </p>
          </div>

          <div className="code-header">
            <span>Terminal &mdash; Local Setup &amp; Offline Demo</span>
            <span>bash</span>
          </div>
          <pre className="code-block">
{`# 1. Clone repository and set up virtual environment
git clone https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification.git
cd face-blockchain-verification
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\\Scripts\\Activate.ps1

# 2. Install reproducible dependencies pinned by constraints.txt
pip install -r requirements.txt -c constraints.txt

# 3. Download verified OpenCV Zoo models (SHA-256 checksummed)
python scripts/fetch_models.py

# 4. Verify system environment readiness
python -m src.main doctor --offline

# 5. Run hermetic, offline rehearsal (no API keys, no gas, no network)
python -m src.main register --image tests/data/query.png --fixture tests/data/candidates.json \\
    --engine stub --allow-offline-stub --dry-run

# 6. Verify the generated evidence record
python -m src.main verify --record output/verification.json --dry-run

# 7. (Optional) Run the local-first web interface
pip install -r requirements-web.txt -c constraints.txt
(cd web && npm ci && npm run build)
python -m src.web --demo    # http://127.0.0.1:8765`}
          </pre>
        </div>
      </section>

      {/* 9. Evaluation and Limitations */}
      <section id="evaluation" className="section" style={{ background: "var(--bg-secondary)" }}>
        <div className="container">
          <div className="section-head">
            <span className="section-tag">08 / EMPIRICAL EVALUATION</span>
            <h2 className="section-title serif">Measured Results &amp; Disclosed Limits</h2>
            <p className="section-desc">
              All benchmarks were run against the public Labeled Faces in the Wild (LFW) dataset using raw, unaligned images through the complete detection and embedding pipeline.
            </p>
          </div>

          {/* Interactive Engine Selector */}
          <div style={{ display: "flex", gap: "8px", marginBottom: "20px" }}>
            <button
              onClick={() => setSelectedEngine("sface")}
              className={`nav-button ${selectedEngine === "sface" ? "badge-sage" : ""}`}
              style={{ cursor: "pointer", fontWeight: selectedEngine === "sface" ? 600 : 400 }}
            >
              OpenCV SFace (Default)
            </button>
            <button
              onClick={() => setSelectedEngine("r50")}
              className={`nav-button ${selectedEngine === "r50" ? "badge-navy" : ""}`}
              style={{ cursor: "pointer", fontWeight: selectedEngine === "r50" ? 600 : 400 }}
            >
              ArcFace ResNet-50 (Recommended)
            </button>
            <button
              onClick={() => setSelectedEngine("r100")}
              className={`nav-button ${selectedEngine === "r100" ? "badge-oxblood" : ""}`}
              style={{ cursor: "pointer", fontWeight: selectedEngine === "r100" ? 600 : 400 }}
            >
              ArcFace ResNet-100
            </button>
          </div>

          <div style={{ textAlign: "center", marginBottom: "36px" }}>
            <img
              src="./assets/benchmark.svg"
              alt="LFW Face Recognition Benchmark Comparison"
              style={{ maxWidth: "100%", height: "auto", border: "1px solid var(--rule-base)", background: "#faf6ea", borderRadius: "3px" }}
            />
          </div>

          {/* Benchmark Table */}
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Metric / Test Condition</th>
                  <th>SFace (OpenCV, Apache-2.0)</th>
                  <th>ArcFace-R50 (InsightFace)</th>
                  <th>ArcFace-R100 (InsightFace)</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>10-Fold Accuracy (LFW)</strong></td>
                  <td>99.32% &plusmn; 0.36</td>
                  <td><strong>99.65% &plusmn; 0.29</strong></td>
                  <td>99.63% &plusmn; 0.29</td>
                </tr>
                <tr>
                  <td><strong>Equal Error Rate (EER)</strong></td>
                  <td>0.83%</td>
                  <td><strong>0.60%</strong></td>
                  <td>0.67%</td>
                </tr>
                <tr>
                  <td><strong>TAR @ FAR = 1e-3</strong></td>
                  <td>98.47%</td>
                  <td><strong>99.33%</strong></td>
                  <td>99.30%</td>
                </tr>
                <tr>
                  <td><strong>Downscale 5x Probe Stress</strong></td>
                  <td>94.3%</td>
                  <td><strong>99.5%</strong></td>
                  <td>99.3%</td>
                </tr>
                <tr>
                  <td><strong>Rotate 30&deg; Probe Stress</strong></td>
                  <td>90.2%</td>
                  <td><strong>99.7%</strong></td>
                  <td>99.5%</td>
                </tr>
                <tr>
                  <td><strong>Inference Latency (1280px)</strong></td>
                  <td>169 ms (CPU)</td>
                  <td><strong>21 ms (RTX 4050 GPU)</strong></td>
                  <td>26 ms (RTX 4050 GPU)</td>
                </tr>
                <tr>
                  <td><strong>Licensing &amp; Commercial Rights</strong></td>
                  <td><span className="badge badge-sage">Permissive (Apache-2.0)</span></td>
                  <td><span className="badge badge-oxblood">Non-Commercial Research</span></td>
                  <td><span className="badge badge-oxblood">Non-Commercial Research</span></td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Honest Disclosures */}
          <div className="grid-2" style={{ marginTop: "32px" }}>
            <div className="card">
              <span className="card-tag">EVALUATION CAVEATS</span>
              <h3 className="card-title serif">What Was NOT Measured</h3>
              <p className="card-desc">
                LFW is saturated. Performance on IJB-C, CFP-FP, AgeDB, or extreme occlusions was <strong>not measured</strong>. No demographic breakdown or fairness claims are made. Geometric verification was tested on synthetic image fixtures only; repetitive real-world textures (architectural facades, repeated text) can create spurious inliers.
              </p>
            </div>

            <div className="card">
              <span className="card-tag">DEPLOYMENT REALITY</span>
              <h3 className="card-title serif">Contract &amp; Public Status</h3>
              <p className="card-desc">
                <strong>Registry v3 is compiled and tested on an in-process EVM; it has not been deployed publicly to Base Sepolia testnet.</strong> No transaction funds have been spent. The repository currently lacks a root LICENSE file (the Solidity contract MIT tag does not license the Python codebase).
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 10. Final CTA & Footer */}
      <footer className="site-footer">
        <div className="container">
          <div className="footer-grid">
            <div>
              <div className="brand-group" style={{ marginBottom: "16px" }}>
                <span className="brand-stamp">EVIDENCE RECORD</span>
                <span className="brand-title">FaceProof</span>
              </div>
              <p style={{ maxWidth: "340px", lineHeight: "1.6", color: "var(--ink-secondary)" }}>
                An evidence-first image provenance architecture linking local computer vision, cryptographic record sealing, and blockchain commitments.
              </p>
            </div>

            <div>
              <h4 className="footer-col-title serif">Documentation</h4>
              <ul className="footer-links">
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/docs/PIPELINE.md" target="_blank" rel="noopener noreferrer">Pipeline Specification</a></li>
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/docs/RECORD_FORMAT.md" target="_blank" rel="noopener noreferrer">Record Format v2</a></li>
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/docs/EVALUATION.md" target="_blank" rel="noopener noreferrer">Empirical Evaluation</a></li>
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/docs/BASE_SEPOLIA_RELEASE.md" target="_blank" rel="noopener noreferrer">Base Sepolia Guide</a></li>
              </ul>
            </div>

            <div>
              <h4 className="footer-col-title serif">Repository</h4>
              <ul className="footer-links">
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification" target="_blank" rel="noopener noreferrer">GitHub Source</a></li>
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/SECURITY.md" target="_blank" rel="noopener noreferrer">Security Policy</a></li>
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/CHANGELOG.md" target="_blank" rel="noopener noreferrer">Changelog (v2.0.0)</a></li>
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener noreferrer">Contributing Guide</a></li>
              </ul>
            </div>

            <div>
              <h4 className="footer-col-title serif">Publications</h4>
              <ul className="footer-links">
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/docs/articles/faceproof-engineering-story.md" target="_blank" rel="noopener noreferrer">Technical Article</a></li>
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/docs/LAUNCH_CHECKLIST.md" target="_blank" rel="noopener noreferrer">Launch Checklist</a></li>
                <li><a href="https://github.com/satyamshrivastav955-dotcom/face-blockchain-verification/blob/main/docs/RELEASE_NOTES.md" target="_blank" rel="noopener noreferrer">Release Notes</a></li>
              </ul>
            </div>
          </div>

          <div className="footer-bottom">
            <span>&copy; 2026 FaceProof Engineering Release &middot; Research &amp; Portfolio Release</span>
            <span>Public Showcase Deployment: <code>https://satyamshrivastav955-dotcom.github.io/face-blockchain-verification/</code></span>
          </div>
        </div>
      </footer>
    </div>
  );
}
