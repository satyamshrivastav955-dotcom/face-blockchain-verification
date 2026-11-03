<div align="center">

<img src="assets/readme/hero.svg" alt="FaceProof: the receipts for where an image appeared" width="100%"/>

<br/>

![Python](https://img.shields.io/badge/python-3.10%2B-24364f?style=flat-square&labelColor=211c16)
![OpenCV](https://img.shields.io/badge/OpenCV-YuNet%20%2B%20SFace-2e5842?style=flat-square&labelColor=211c16)
![ONNX Runtime](https://img.shields.io/badge/ONNX%20Runtime-SCRFD%20%2B%20ArcFace-86281f?style=flat-square&labelColor=211c16)
![C2PA](https://img.shields.io/badge/C2PA-content%20credentials-9e6b14?style=flat-square&labelColor=211c16)
![Solidity](https://img.shields.io/badge/Solidity-0.8.24-24364f?style=flat-square&labelColor=211c16)
![Registry v3](https://img.shields.io/badge/registry%20v3-tested%2C%20not%20deployed-7a6f5d?style=flat-square&labelColor=211c16)

**Image provenance, kept on file.**<br/>
Seal a signed, time-stamped description of an image that anyone can check in their own browser without trusting you, and never claim to know who is in it. Optionally, trace where an image appeared and say plainly whether a hit is a *face match* or only *image similarity*.

[Landing page](#the-app) · [Pipeline](#the-pipeline) · [Measured results](#measured-results) · [Quickstart](#quickstart) · [CLI](#cli) · [Security](#security-and-privacy) · [Limits](#what-is-not-done-and-what-is-not-claimed)

</div>

> [!IMPORTANT]
> **This is an image-provenance tool, not an identity-recognition product.** It never maps a face to a person. A record says *what the pipeline measured* and *that its hash was registered at a time*. It does not prove a claim is true, that a page is authentic, or who appears in a photograph.

---

## The core: attest, then verify anywhere

```bash
python -m src.main keygen --out ~/faceproof-key.pem                 # once; keep it outside the repo
SIGNING_KEY_FILE=~/faceproof-key.pem python -m src.main attest --image photo.jpg --sign \
    --anchor ots --consent-timestamp-calendars                      # sends only the 32-byte record hash
python -m src.main ots-upgrade --record output/attestation.json     # hours later: adds the Bitcoin attestation
python -m src.main verify --record output/attestation.json --image photo.jpg --require-image --trusted-key <author public key>
```

`attest` never detects, embeds or compares a face, and works with no network at all unless you ask for a timestamp. The record holds the file's SHA-256, a pHash, the
C2PA state, and any *declared* synthetic-media metadata. It holds no face data and no filename. A signature says which key authored it; a Bitcoin timestamp (OpenTimestamps) says the record
existed by a block; the exact image binding says it is *that file*. Each is a separate, individually reported check, and a missing one is never a pass.

<div align="center">
<img src="assets/readme/verifier.png" alt="The static verifier page showing a verified record, four passing checks and the network log" width="620"/>

<sub>The static verifier (<code>web/dist-verifier</code>), checking the generated <i>test vectors</i> (a test key and a <b>fabricated</b> block header, not real evidence). It runs entirely in the browser; the log lists every request it made.</sub>
</div>

**Tamper demonstration** (offline, real code, six forgeries, exit 0 only if all are rejected):

```bash
python -m src.main tamper-demo --suite attestation --image tests/data/query.png
```

```text
  [OK] control                  CONTROL   hash, signature and image all pass
  [OK] 1 naive edit             REJECTED  [local_integrity] the payload does not match its stored hash
  [OK] 2 re-sealed edit         REJECTED  [signature] signature covers a different hash than the payload now has
  [OK] 3 forged by another key  REJECTED  [signature] valid signature, but by a key that is not in the trusted set (...)
  [OK] 4 one pixel edited       REJECTED  [image_binding] image digest differs from the record
  [OK] 5 re-encoded copy        REJECTED  [image_binding] image digest differs ... (pHash distance 10/64: visually the same, not the attested bytes)
  [OK] 6 signature stripped     REJECTED  [signature] a trusted key was required but the record is unsigned
```

**Measured, on real photographs** (300 LFW sources; full tables, intervals and limits in [BENCHMARKS.md](BENCHMARKS.md) B7). The 12-way mean is not reported; read the table, not a headline.
The near-copy test (pHash OR geometric) accepted **every edited copy at >= 99%** for all 12 transformations (identical, JPEG q50/q20, resize 50%/25%, blur, brightness, crop 90%/70%, rotate 10 degrees, mirror, screenshot-like re-capture; 99.0% [97.1, 99.7] for the screenshot-like one, 100% for the rest),
and accepted **0 of 600 unrelated photos** (95% upper bound about 0.5%). pHash alone misses crops, rotations, mirrors and screenshots; the geometric stage is what recovers them. Exact SHA-256 binding accepted 0 of 3,300 edited copies, by design.
This says nothing about phone photos, screenshots of text or UI, logos or repeated textures (where false matches are likeliest), or stacked edits.

Threat model: [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md). Privacy and legal posture (incl. India's DPDP Act, from secondary sources): [docs/PRIVACY.md](docs/PRIVACY.md).

## At a glance

<table>
<tr>
<td width="33%" valign="top">

**Honest evidence**<br/>
Every accepted candidate carries exactly one label: *face match* or *image derivative*. A hash-only match is never described as a face match, and a check that could not run is *inconclusive*, never a pass.

</td>
<td width="33%" valign="top">

**Local by default**<br/>
Detection, embedding, re-checking, hashing and verification run on your machine. Search and public upload are opt-in, per run, with the exact data flow shown first.

</td>
<td width="33%" valign="top">

**Measured, not claimed**<br/>
Models are benchmarked on public LFW, stress-tested, and the raw results are in the repo. What was *not* measured is listed as plainly as what was.

</td>
</tr>
</table>

## The app

A local web app over the same pipeline — React + TypeScript frontend, FastAPI backend, loopback-only. Nothing in it is mocked: stages, scores, records and manifests are the pipeline's real output.

<div align="center">
<img src="assets/readme/landing_hero.png" alt="FaceProof landing page" width="860"/>
</div>

<details>
<summary><b>Watch a full run</b> — mount an image, examine, seal, then examine the sealed record</summary>
<br/>
<div align="center">
<img src="assets/readme/demo.gif" alt="Recorded demo run: mount the synthetic sample, begin examination, examine the sealed record" width="760"/>

<sub>Real capture of the app in <b>demo mode</b> (stub engine, synthetic fixture, simulated ledger), produced by <code>scripts/capture_screenshots.py</code>.</sub>
</div>
</details>

<table>
<tr>
<td width="50%" valign="top">
<img src="assets/readme/workspace_intake.png" alt="Case file: image mounted, disclosure and consent notice"/>
<sub><b>Open a case.</b> Image mounted; the disclosure notice states exactly what a provider would receive before anything is sent.</sub>
</td>
<td width="50%" valign="top">
<img src="assets/readme/examination.png" alt="Record examination: six numbered checks and a VERIFIED stamp"/>
<sub><b>Examine a record.</b> Six numbered checks resolve one by one; <i>NOT CHECKED</i> and <i>COULD NOT RUN</i> are never shown as a pass.</sub>
</td>
</tr>
</table>

<details>
<summary><b>A finished case</b> — proceedings, schedule of candidates, finding sheet</summary>
<br/>
<div align="center"><img src="assets/readme/workspace_result.png" alt="Finished case: schedule of candidates with rejections kept, and the finding sheet with seal and stamp" width="560"/></div>
<sub>Rejections stay in the schedule. The finding carries its statement, its reservations, the engine and licence, the content-credentials state and the seal. This demo run is labelled <i>test-only</i> and <i>simulated</i> because it is.</sub>
</details>

```bash
pip install -r requirements-web.txt -c constraints.txt
(cd web && npm ci && npm run build)
python -m src.web            # http://127.0.0.1:8765, loopback only
python -m src.web --demo     # adds the stub engine + synthetic fixture, labelled on every screen
```

### Public showcase website

The local web app above is strictly local-first and loopback-only. For public presentation, a decoupled static showcase website is located in [`showcase/`](showcase/) and configured for GitHub Pages deployment. It contains zero backend dependencies, zero private credentials, and communicates architectural concepts and benchmarks cleanly. See [docs/SHOWCASE_DEPLOYMENT.md](docs/SHOWCASE_DEPLOYMENT.md).

## The pipeline

<div align="center">
<img src="assets/readme/pipeline.svg" alt="Pipeline: detect, embed, search, download, re-examine, seal, anchor, with where each stage runs" width="100%"/>
</div>

| Stage | What it does | Why this way |
|---|---|---|
| **Detect** | SCRFD-10G with 5-point landmarks, multi-scale letterbox, low-threshold retry when nothing is found | Current detector generation; recovers hard faces without extra inference |
| **Embed** | Least-squares similarity alignment → ArcFace (R50 / R100), 512-d, flip test-time augmentation, ONNX Runtime (CUDA if present) | ArcFace-family accuracy; `opencv` (YuNet + SFace) remains the permissive default |
| **Subject** | Face with the highest *prominence* (size × centrality); warns when a second face is comparable | Measured: "largest face" is wrong often enough to cost 2.4 points of accuracy |
| **Search** | Reverse-image provider returns *leads*, never findings | Needs explicit consent; failures are errors, never "no match" |
| **Download** | SSRF-guarded (IP-pinned, redirect-checked, size/pixel-bounded), bounded parallel pool | 4× faster at simulated latency; results still consumed in order |
| **Re-examine** | Face cosine, geometric verification (SIFT + RANSAC), pHash — per candidate | Three tiers of evidence, each labelled for what it can and cannot show |
| **Seal** | Restricted RFC 8785 canonical JSON → SHA-256; schema `faceverify/v2` | Deterministic, honestly named; old records still verify under their own rules |
| **Anchor** | One transaction per record, or one Merkle root for many | Hash + keccak256(URL) only; never a face, vector or URL |

### Evidence ladder

<div align="center">
<img src="assets/readme/evidence_ladder.svg" alt="Evidence ladder: face match, geometric image derivative, pHash image derivative" width="100%"/>
</div>

* **Geometric verification** recovers what a 64-bit pHash misses — crops, rotations, mirrored copies — and is *explainable*: the record stores how many local features agree on one transform. It was validated on synthetic images only; repeated textures, text and logos in real photos can create spurious matches (stated in the record's reservations).
* **C2PA Content Credentials** on the source and matched image are read as independent provenance evidence. `valid` means signature and hashes verify, **not** that the signer is trusted (reported separately); `absent` proves nothing; `ai_generated` is only what the signer's manifest declares.
* Selection among candidates is deterministic: face match → social domain → higher cosine → lower pHash → provider position → URL, independent of input order.

## Measured results

<div align="center">
<img src="assets/readme/benchmark.svg" alt="Benchmark: SFace versus ArcFace on LFW, accuracy, true accepts at FAR 1e-3, stressed probes and latency" width="100%"/>
</div>

Full LFW protocol (6,000 pairs, 7,701 **raw, unaligned** images through the full detect → align → embed path), 10-fold cross-validated. The chart is drawn from [`docs/results/lfw_benchmark.json`](docs/results/lfw_benchmark.json) by `scripts/make_readme_assets.py`; reproduce with `scripts/benchmark_face.py`.

| | SFace (MIT / Apache-2.0) | ArcFace-R50 | ArcFace-R100 |
|---|---|---|---|
| 10-fold accuracy | 99.32% ± 0.36 | **99.65% ± 0.29** | 99.63% ± 0.29 |
| EER | 0.83% | **0.60%** | 0.67% |
| True accepts @ FAR 1e-3 | 98.47% | **99.33%** | 99.30% |
| Probe downscaled 5× | 94.3% | **99.5%** | 99.3% |
| Probe rotated 30° | 90.2% | **99.7%** | 99.5% |
| Latency, 1280 px | 169 ms (CPU) | **21 ms (GPU)** | 26 ms (GPU) |

**Read this honestly.** LFW is near-saturated — the clean-accuracy gap is small and R100 is not better than R50 here; the stressed probes and the FAR-1e-3 point are where the newer models clearly separate. The GPU/CPU latency comparison is of *setups* (RTX 4050 laptop GPU vs this CPU), not of models. Each stress cell is 600 pairs, so ~1-point differences are noise. SFace's documented threshold (0.363) landed almost exactly on its measured FAR-1e-3 point (0.359) — an independent sanity check. IJB-C, CFP-FP, AgeDB, masks, age gaps and any demographic breakdown were **not** measured, and no fairness claim is made. Details and every caveat: [docs/EVALUATION.md](docs/EVALUATION.md).

> [!WARNING]
> **Licences.** The ArcFace/SCRFD weights come from the InsightFace project for **non-commercial research use only**. The licence is written into every record and printed by the CLI; the default engine (`opencv`) is permissively licensed.

### Merkle-batched anchoring

<div align="center">
<img src="assets/readme/merkle.svg" alt="Merkle batch: one transaction anchors many records; each record keeps a logarithmic inclusion proof" width="100%"/>
</div>

`register --anchor-mode batch` seals records without anchoring; `anchor-batch` registers one RFC 6962 root for all of them and writes each record its inclusion proof. The leaf binds the URL commitment, so a valid proof also proves the URL matches. Measured on an in-process EVM: one record **74,464** gas; a batch of 1 **74,174**; a batch of 1,000 **74,186** — about **74 gas per record**. Real chains add calldata and L1-data fees, which this does not model. The tree matches Certificate Transparency reference values, an independent implementation and exhaustive proofs. **Registry v3 is compiled and tested, not deployed** — see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt -c constraints.txt       # tested, pinned versions
python scripts/fetch_models.py                           # OpenCV Zoo models, SHA-256 verified
python -m src.main doctor --offline
```

**Offline demo — no network, no keys, no gas.** Exercises everything except real recognition, a real search and a real chain, and cannot be mistaken for the real thing: the record is labelled test-only and simulated.

```bash
python -m src.main register --image tests/data/query.png --fixture tests/data/candidates.json \
    --engine stub --allow-offline-stub --dry-run
python -m src.main verify --record output/verification.json --dry-run
```

Real excerpt from running exactly that (this checkout, 2026-10-30):

```text
    C2PA Content Credentials: absent (absence proves nothing)
  [1/2] x.com: FACE MATCH  cos=1.0000  pHash= 8/64  faces=1  [social]
  [2/2] example.org: rejected    cos=-0.0494  pHash=37/64  faces=1
  [OK] payload canonicalized (3385 bytes, sha256-jcs-rfc8785-restricted-v1)
-> Anchoring (SIMULATED local chain)
  [OK] RECORD VERIFIED: UNMODIFIED, ANCHORED, URL COMMITMENT MATCHES
    Passed: hash recomputation, chain anchor, URL commitment.
    Not checked: image_binding, evidence_bundle, merkle_inclusion.
    SIMULATED: this was checked against a local JSON file, NOT a blockchain.
    TEST-ONLY: the record itself came from a stub engine/fixture.
```

(The stub scores 1.0000 because its "face" is the whole synthetic image — that is why it is called a stub.)

**Higher-accuracy engines (optional, non-commercial weights):**

```bash
python scripts/fetch_insightface.py        # SCRFD + ArcFace; checksum-pinned, atomic
python -m src.main register --image photo.jpg --engine auto ...   # best available; r50 preferred
```

**A real run** sends data to third parties, so it needs flags that say so:

```bash
python -m src.main register --image photo.jpg --consent-external-search --image-url https://you.example/photo.jpg
```

Without consent the command prints what *would* be sent and stops — `nothing has been sent`.

## CLI

| Command | Purpose |
|---|---|
| `keygen` · `attest` | Create an Ed25519 key; seal an image-only record (no face, no network by default), optionally `--sign` and `--anchor ots` |
| `ots-upgrade` | Fetch the Bitcoin attestation for a pending OpenTimestamps record |
| `c2pa-embed` · `c2pa-check` | Embed a signed C2PA manifest that references a record; read Content Credentials (with your own trust anchors) |
| `register` | Full pipeline (face trace); `--engine`, `--anchor-mode single\|batch`, `--require-face-match`, `--minimal-evidence`, consent flags |
| `anchor-batch` | One Merkle-root transaction for many sealed records (needs registry v3) |
| `verify` | Recompute, bind to an image, check the bundle, look up the chain; `--json` for machines |
| `tamper-demo` | `--suite record`: naive vs re-sealed edit (needs a ledger). `--suite attestation --image X`: six offline forgeries |
| `search` | Search stage only |
| `doctor` | Readiness; never prints a secret |
| `purge-evidence` | Delete old local bundles (dry run by default) |
| `deploy` | Compile / deploy the registry; refuses to spend gas without `--yes` |

| Exit | Meaning |
|---|---|
| 0 | verified / success |
| 1 | error (config, consent refused, provider failure, malformed record) |
| 2 | local failure: modified payload, wrong image, bad bundle, unsupported algorithm |
| 3 | not anchored |
| 4 | anchor conflict (URL commitment or inclusion proof) |
| 5 | no confirmed match |
| **6** | **inconclusive** — a required check could not run (RPC down, incompatible contract, failed lookup). Never a pass. |

## Security and privacy

<details>
<summary><b>Network:</b> SSRF-guarded fetching of untrusted URLs</summary>

Only `http(s)` on ports 80/443, no credentials; every hop including redirects (max 3, manual, loop-checked) is re-validated; every resolved address must be globally routable (IPv4/IPv6, mapped/6to4/NAT64/Teredo unwrapped); the TCP connect is **pinned to the validated IP** (DNS-rebinding); proxies and environment are ignored; 25 MiB, 20 s per request, 45 s total, image content types only. Headers are read before decoding (≤ 16384 px per side, ≤ 50 MP). A real loopback server is unreachable through the guarded session (tested). *Residual:* trusts the OS resolver; a public host can still serve hostile content.
</details>

<details>
<summary><b>Consent:</b> nothing leaves the machine without a flag</summary>

External search and public upload each need their own flag; `PUBLISH_PROVIDER` defaults to `none`; the disclosure names the service and what it receives. No retention or deletion promise is made for any third party. `--minimal-evidence` keeps no face crops or downloaded bytes; rejected candidates' bytes are never kept; `purge-evidence` removes old bundles.
</details>

<details>
<summary><b>Chain:</b> what goes on the public ledger</summary>

Calldata is exactly selector + two `bytes32` (single) or selector + root + size (batch); events carry only hashes. The URL is never sent — only `keccak256(url)`, which is not secret against guessing and does not prove authenticity. Embeddings are never saved, sent or written on-chain; the stored fingerprint is a *commitment*, not anonymisation. Duplicate, zero and unknown cases, chain-id mismatch, reverted receipts and RPC timeouts are all tested on an in-process EVM.
</details>

<details>
<summary><b>Verification fails closed</b></summary>

`verified` requires every check the claim needs to have run **and passed**. An unreachable chain, a v1/incompatible contract or a failed commitment lookup is *inconclusive* (exit 6). Unknown integrity algorithms fail; historical records verify under their original rules and are never re-interpreted. Canonicalization is a *restricted* RFC 8785 profile and is named as such.
</details>

<details>
<summary><b>Web app</b></summary>

Loopback by default; `Host`/`Origin` checks; uploads ≤ 10 MiB validated as bounded images; one worker and a short queue; per-job temp directories deleted on request, after 1 h and on shutdown; only whitelisted artefacts served; real-chain writes need `--allow-chain-writes`; no stack traces or secrets in responses. There is **no authentication**: do not expose it.
</details>

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SEARCH_PROVIDER` | `serpapi_lens` | `serpapi_lens` · `tineye` · `local_fixture` (offline) |
| `SERPAPI_KEY` / `TINEYE_API_KEY` | – | provider keys |
| `PUBLISH_PROVIDER` | `none` | public image host, only with `--consent-public-upload` |
| `RPC_URL` · `CHAIN_ID` · `CHAIN_NAME` · `EXPLORER_BASE` | Base Sepolia | target chain; chain-id mismatch is refused |
| `PRIVATE_KEY` | – | **burner** key; only for deploy/register, never for verification |
| `SIGNING_KEY_FILE` | – | Ed25519 PEM used by `--sign` (outside the repo) |
| `OTS_CALENDARS` · `OTS_EXPLORERS` | public defaults | OpenTimestamps calendars; block-explorer APIs for header checks |
| `C2PA_TRUST_ANCHORS_FILE` | – | PEM of C2PA trust anchors you downloaded; empty = no signer is ever trusted |
| `CONTRACT_ADDRESS` | – | a registry v2 or v3 deployment (v1 is detected and rejected) |
| `FACE_COSINE_THRESHOLD` | per engine | if unset, each engine's benchmarked default (SFace 0.363, R50 0.25, R100 0.28) |
| `PHASH_MAX_DISTANCE` | `12` | 0–64 |
| `MAX_CANDIDATES` | `25` | 1–100 |
| `EVIDENCE_RETENTION_DAYS` | `0` | default for `purge-evidence`; nothing is deleted automatically |
| `PROJECT_DIR` | repo root | where `models/`, `output/`, `evidence/` live |

## Engineering

```bash
python -m pytest tests -q                              # hermetic: no network, keys, wallet or gas
pip install -r requirements-dev.txt                    # + pytest, ruff, mypy (pure wheels)
pip install -r requirements-evm.txt                    # + in-process EVM for contract tests (Linux/macOS/WSL; needs a C toolchain on Windows)
ruff check src tests scripts && ruff format --check src tests scripts && mypy
(cd web && npm ci && npm run build)
python scripts/make_readme_assets.py                   # regenerate the SVGs (benchmark from the JSON)
python scripts/capture_screenshots.py                  # regenerate screenshots + GIF from the live app
```

As of 2026-11-03: **713 passed, 1 skipped** on Windows 11 / Python 3.13.13 from `requirements-dev.txt` + `constraints.txt` (the skip is the in-process-EVM contract module, which needs `requirements-evm.txt` and a C toolchain on Windows), including 4 real-browser tests of the verifier page; **732 passed, 8 skipped** on Ubuntu (WSL, Python 3.13) with the EVM module running (skips: Playwright, the git-ignored C2PA sample, `node`); `cd web && npm test` runs 13 verifier tests; ruff, ruff format and mypy are clean. CI fails if the contract tests skip. Coverage includes every match outcome and boundary, deterministic selection, fail-closed verification, SSRF/redirect/size/decode limits, consent gates and secret redaction, record and bundle tampering, RFC 8785 vectors with a JavaScript cross-check, RFC 6962 reference values, contract behaviour (duplicates, zero values, v1/v2/v3 detection, calldata and events, gas), SCRFD decode and alignment, geometric verification, C2PA (including a real signed sample and a tampered copy) and download concurrency.

`.github/workflows/ci.yml` runs lint, format, mypy, tests and contract compilation on Python 3.11–3.13 plus the frontend build, with no secrets and no `continue-on-error`. In previous CI runs, frontend build and Python 3.12/3.13 succeeded while Python 3.11 failed during pip install due to `numpy==2.5.4` requiring Python >= 3.12; `constraints.txt` was subsequently patched to `numpy==2.2.6` to restore full Python 3.11–3.13 matrix compatibility. `ruff format` is enforced for new or rewritten files; older modules are listed as exclusions in `pyproject.toml`.

| Document | What is in it |
|---|---|
| [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) | Attack matrix with the control, the test and the residual risk for each row |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Biometric handling, DPDP summary, deletion, no-identification rule |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Why OpenTimestamps over a testnet registry, why no AI detector, and the other major choices |
| [BENCHMARKS.md](BENCHMARKS.md) | Every number quoted anywhere, with the command that reproduces it |
| [docs/ROADMAP.md](docs/ROADMAP.md) | State and next steps |
| [docs/INTERVIEW_PACK.md](docs/INTERVIEW_PACK.md) | Pitch, whiteboard architecture, hard questions |
| [docs/PIPELINE.md](docs/PIPELINE.md) | Design of each stage and the decisions behind it |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Benchmarks, stress tests, thresholds, and every caveat |
| [docs/RECORD_FORMAT.md](docs/RECORD_FORMAT.md) | Record schema, algorithm labels, anchor modes, bundles, migration |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Registry v2/v3, manual deployment, migration from v1 |
| [docs/BASE_SEPOLIA_RELEASE.md](docs/BASE_SEPOLIA_RELEASE.md) | Base Sepolia deployment guide, burner wallet, and verification checklist |
| [docs/SHOWCASE_DEPLOYMENT.md](docs/SHOWCASE_DEPLOYMENT.md) | GitHub Pages showcase architecture and manual deployment guide |
| [docs/LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md) | Complete pre-flight and release verification checklist |
| [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md) | v2.0.0 capabilities, migration, and known boundaries |
| [docs/articles/faceproof-engineering-story.md](docs/articles/faceproof-engineering-story.md) | Publication-quality deep dive technical article |

## What is not done, and what is not claimed

* **The OpenTimestamps round trip is only half proven on a live network.** On 2026-11-03 one record hash (a synthetic sample image; [docs/examples/live-ots-attestation.json](docs/examples/live-ots-attestation.json)) was accepted by all three public calendars, and `verify` correctly reports it `PENDING` (exit 3). The Bitcoin confirmation, `ots-upgrade` and the final `verified` result were **not yet observed**; run `ots-upgrade` on that file after a few hours. The Bitcoin-header check itself is tested only against a fabricated header.
* **There is no AI-image detector**, on purpose. "Synthetic-media signals" are declarations read from metadata, labelled as such; their absence proves nothing.
* **Both container images build and start** (verifier: CSP headers served; API: healthy, runs as a non-root user, `/api/attest` and `/verifier/` answer, a wrong `Host` header is refused). The smoke test found and fixed a missing OpenCV system library. **CI has never run on GitHub.**
* **The verifier page checks exact bytes only** (no pHash, no face model, no EVM lookups) and trusts public block explorers for Bitcoin headers unless you verify the `.ots` with your own node.
* **Signing keys are unencrypted at rest**; no rotation or revocation.
* **The real-photo evaluation covers one kind of photo** (LFW portraits, 250 px) and no stacked edits.

* **Registry v3 is not deployed.** It is compiled and tested on an in-process EVM; a real deployment is a manual, deliberate step. A plaintext URL ever sent to an old v1 contract stays public.
* **Face matching is measured on LFW only.** No IJB-C / CFP-FP / AgeDB, no demographic breakdown, one machine. Thresholds are indicative, not calibrated for any population.
* **Geometric verification is validated on synthetic images.** Real photographs may produce false matches (repeated structure, text, logos).
* **One search-provider path is verified end to end** (offline fixture); live SerpApi/TinEye calls need your keys and were not exercised here.
* **The web app is a single-user local tool:** no accounts, no persistence beyond an hour, no hosting setup. The public website is a static showcase on GitHub Pages.
* **Smart contract deployment is manual;** testnet funds are never spent automatically.
* **There is no `LICENSE` file.** The contract carries an MIT SPDX tag, which does not license the rest. Choosing a licence is the owner's decision. Third-party: OpenCV (Apache-2.0); OpenCV Zoo YuNet (MIT) and SFace (Apache-2.0); InsightFace weights (**non-commercial research**); c2pa-python, web3.py and others under their own licences.
* Use only images you have the right to process and obtain consent from the people shown. Do not use this to identify, track or profile anyone. A record is not legal proof of anything.

<details>
<summary><b>Earlier screenshots in <code>assets/</code></b> (kept as history)</summary>
<br/>

`assets/demo_confirmed_match.png` and `assets/demo_rejected_claim.png` come from an **earlier build** (older wording, contract v1 interface). The command visible in them includes `--dry-run`, so **those anchors used the simulated chain, not Base Sepolia**, and they show other people's photographs from public posts — consider whether to keep them in a public repository. `assets/terminal_card.svg` is a hand-authored illustration, not a captured session. None of these are evidence of current behaviour or of any on-chain transaction. The current screenshots above are generated by `scripts/capture_screenshots.py` from the live app.
</details>

<div align="center"><sub>FaceProof · local-first image provenance · a record shows what was measured and anchored, not that a claim is true</sub></div>
