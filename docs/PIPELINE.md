# The pipeline: what it does, why each stage is the way it is

Every stage below was chosen against an alternative and, where it could be measured, measured. Numbers
and their limits are in [EVALUATION.md](EVALUATION.md); this page is about the design.

```
 image ──► C2PA read ─────────────────────────────────────────────┐ (independent of everything below)
   │                                                               │
   ├─► SCRFD detect ► 5-pt align ► ArcFace embed ► select subject  │
   │                                                    │          │
   │        search provider(s) ──► candidates ──► guarded, parallel download
   │                                                    │
   │              per candidate:  face cosine ──► FACE MATCH
   │                              pHash ────────► IMAGE DERIVATIVE  (basis: phash)
   │                              SIFT+RANSAC ──► IMAGE DERIVATIVE  (basis: geometric)
   │                                                    │
   └──────────────► sealed record (restricted RFC 8785 + SHA-256) ──► single anchor │ Merkle batch
```

## 1. Face detection and embedding

| | Original | Now (selectable) |
|---|---|---|
| Detector | YuNet (2023, small CPU model) | **SCRFD-10G** with 5-point landmarks, multi-scale letterbox, own decode + NMS |
| Alignment | OpenCV `alignCrop` | least-squares similarity transform (Umeyama) to the ArcFace 112x112 template |
| Embedder | SFace (MobileFaceNet, 128-d) | **ArcFace ResNet-50 / ResNet-100**, 512-d, optional flip test-time augmentation |
| Runtime | OpenCV DNN, CPU | **ONNX Runtime**, CUDA when present (CPU fallback), providers reported |
| Threshold | 0.363 (OpenCV's documented example; measured FAR-1e-3 point on LFW: 0.359) | per engine: FAR-1e-3 point on LFW plus a ~0.03 margin (0.25 / 0.28) |

`--engine opencv|arcface-r50|arcface-r100|auto`. `auto` picks the best engine whose weights are present.
Engines carry `commercial_use` and `model_license`; both go into every record, and the CLI prints the licence
whenever a non-commercial engine is used. **The InsightFace weights are non-commercial research only** — the
permissive `opencv` engine remains the default for exactly that reason.

### Choosing the subject face (a measured decision)

A group or street photo contains several faces. The first version used "the largest". On LFW that is wrong
often enough to matter: SCRFD finds more than one face in about 20% of LFW images (1,527 of 7,701), and scoring the largest instead of
the subject costs ArcFace-R50 2.4 points (97.3% vs 99.7% accuracy). The pipeline now
ranks faces by **prominence** — `sqrt(area)` weighted by closeness to the image centre — and warns when a second
face is within 60% of the winner so the user knows which face was used. Candidates are different: the query is
scored against *every* face in a candidate, so a subject in a crowd is not missed.

## 2. Evidence for "this is the same image" — three tiers

1. **Face match** — a face in the candidate scores at or above the engine's threshold.
2. **Image derivative, geometric basis** — SIFT keypoints + Lowe ratio test + RANSAC homography, tried as-is
   and mirrored. Accepted only with >= 25 inliers, inlier ratio >= 0.30 and a non-degenerate transform. This
   recovers the crops, rotations and mirrored copies that a 64-bit pHash misses, and is *explainable*: the record
   stores `geometric_inliers` / `geometric_matches`.
3. **Image derivative, pHash basis** — the original 64-bit DCT hash within the distance limit.

Tiers 2 and 3 are labelled "image derivative" and never described as a face match. Geometric matching runs only
when the face test and pHash both failed (it is the expensive one). Its weakness is stated in the record:
repeated textures, text and logos can create spurious feature matches.

## 3. Content Credentials (C2PA)

The source image and the matched candidate are checked for a C2PA manifest. This is the industry provenance
standard (signed, tamper-evident metadata written by cameras, editors and generative-AI tools) and it is evidence
that needs no search engine, no face model and no hash. `valid` means the signature and hashes verify, **not** that
the signer is trusted (`untrusted_signer` is reported separately); `absent` is the common case and proves nothing;
`ai_generated` is only what the signer's manifest declares.

## 4. Download and orchestration

Candidate pages are untrusted input (SSRF-guarded, size- and pixel-bounded, redirects re-validated). Downloads are
I/O-bound, so they run in a bounded pool a few candidates ahead of analysis; results are still consumed in order,
so output and selection are deterministic. With *simulated* 150 ms latency, 8 candidates take 0.31 s with 4
workers instead of 1.21 s sequentially (`tests/test_download_concurrency.py`; real network latency not measured).

## 5. Sealing and anchoring

The record is canonicalised (a **restricted** RFC 8785 profile, named as such), hashed with SHA-256 and anchored.
Two modes:

* **single** — one transaction per record (registry v2/v3 `register`).
* **Merkle batch** — `register --anchor-mode batch`, then `anchor-batch`: one transaction registers the RFC 6962
  root over N records; each record keeps a ~log2(N)-hash inclusion proof, and the leaf binds the URL commitment.
  Gas is that of one transaction however large N is (tested on an in-process EVM). Needs registry v3.

The tree is the Certificate Transparency construction (domain-separated leaf/node hashes) and is checked against
CT reference values, an independent implementation and exhaustive proofs.

## What is deliberately *not* done

* No identity database, no face gallery: this is provenance, not recognition.
* No claim of state-of-the-art accuracy beyond what was measured: LFW is saturated and the face test has not been
  run on IJB-C, CFP-FP or AgeDB (not available here); see EVALUATION.md.
* No "AI image detector": C2PA states what a signer declares; this tool does not guess.
