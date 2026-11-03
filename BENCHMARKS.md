# Benchmarks

Single source of truth for every number quoted in the README or on a resume. A number appears here only if
a command in this repo reproduces it. Detailed methodology and caveats for the face and pHash work live in
[docs/EVALUATION.md](docs/EVALUATION.md); raw LFW output is [docs/results/lfw_benchmark.json](docs/results/lfw_benchmark.json).

## Environment

| | |
|---|---|
| Machine | Windows 11 Home 10.0.26300, Intel64 Family 6 Model 191 CPU, NVIDIA RTX 4050 Laptop GPU (6 GB) |
| Python / key libs | 3.13.13, OpenCV 5.0.0.93, NumPy 2.2.6, ONNX Runtime 1.31.1 (LFW run recorded 1.23.2), c2pa-python 0.38.0 |
| Single machine | Cross-machine variance has **not** been measured |

## Status of each result

| ID | Result | Reproduce | Status |
|---|---|---|---|
| B1 | LFW 10-fold: SFace 99.32%, ArcFace-R50 99.65%, R100 99.63% | `python scripts/benchmark_face.py --engines opencv,arcface-r50,arcface-r100 --json out.json` | Taken from the repo's recorded run (2026-10-30). **Not re-run** in the 2026-11-02 audit |
| B2 | Stress tests (downscale, rotate, JPEG, blur, occlusion), 600 pairs each | same script | As B1. ~1-point differences are noise |
| B3 | pHash on synthetic images (12 transforms, 40 images) | `python scripts/evaluate_phash.py --threshold 12 --images 40` | Recorded; synthetic data, shows mechanism only |
| B4 | Geometric verification inliers | `tests/test_geometry.py` | Synthetic mechanism check. **Real-photo results are B7 below** |
| B5 | Gas: single 74,464; Merkle batch ~74 gas/record at N=1000 | `tests/test_registry_evm.py` | Needs `requirements-evm.txt`. Contract tests **ran and passed** on Ubuntu/WSL 2026-11-02 (gas assertions are inside them); exact gas figures not separately printed |
| B6 | Test suite after the 2.1 work: **Windows 713 passed / 1 skipped** (skip = EVM module; includes 4 real-browser tests); **Ubuntu with EVM 732 passed / 8 skipped** (skips: Playwright not installed there, C2PA sample file, `node`); ruff, ruff-format, mypy clean; `npm test` 13/13 | `pytest tests -q`, `ruff check src tests scripts`, `mypy`, `cd web && npm test` | **Re-run 2026-11-03** |
| B7 | Image-derivative recall / false accepts on real photographs (LFW-based labelled set, 300 sources, 3,600 positives, 683 negatives) | `python scripts/evaluate_provenance.py --sources 300 --seed 20261103 --json docs/results/provenance_eval.json` | **Run 2026-11-03**; see section B7 |
| B8 | Browser verifier agrees with the Python reference (canonical bytes, signature, OTS, tamper cases) | `cd web && npm test` (13 tests) and `pytest tests/test_verifier_browser.py` (4 tests, real Chrome) | **Run 2026-11-03**: all pass |
| B9 | Tamper suite: 6 forgeries rejected, control passes | `python -m src.main tamper-demo --suite attestation --image tests/data/query.png` | **Run 2026-11-03**; also in `tests/test_attest_and_signing.py` |

## B7. Image-derivative decision on real photographs (labelled set)

Question: given a source photo S and a candidate C, does the pipeline's derivative test (pHash distance <= 12 OR
SIFT+RANSAC geometric match, the project defaults, untuned) say "C is S, edited or re-encoded"?

* **Reproduce:** `python scripts/fetch_lfw.py` then `python scripts/evaluate_provenance.py --sources 300 --seed 20261103 --json docs/results/provenance_eval.json`
* **Data:** 300 randomly chosen LFW photos (250x250 web news photos; a public research set, not redistributed here).
  Labels are by construction: 12 transformations of S are positives; a random photo of a *different* person and a
  *different photo of the same person* are negatives. No human labelling.
* **Environment:** Python 3.13.13, OpenCV 5.0.0, Windows-11-10.0.26300-SP0; 144.3 s wall time on a shared, busy machine.
* **Statistics:** Wilson 95% intervals; "0 of N" is reported with the rule-of-three upper bound, not as zero.

### Recall on edited copies (true positives; n = 300 each)

| Transformation | pHash only | Geometric only | Pipeline (either) [95% CI] |
|---|---|---|---|
| identical copy | 100.0% (300/300) | 100.0% (300/300) | **100.0% (300/300)** [98.7, 100.0] |
| jpeg q50 | 100.0% (300/300) | 100.0% (300/300) | **100.0% (300/300)** [98.7, 100.0] |
| jpeg q20 | 100.0% (300/300) | 100.0% (300/300) | **100.0% (300/300)** [98.7, 100.0] |
| resize 50% | 100.0% (300/300) | 100.0% (300/300) | **100.0% (300/300)** [98.7, 100.0] |
| resize 25% | 100.0% (300/300) | 85.0% (255/300) | **100.0% (300/300)** [98.7, 100.0] |
| blur sigma 2 | 100.0% (300/300) | 97.3% (292/300) | **100.0% (300/300)** [98.7, 100.0] |
| brightness +30 | 100.0% (300/300) | 100.0% (300/300) | **100.0% (300/300)** [98.7, 100.0] |
| crop 90% | 71.0% (213/300) | 100.0% (300/300) | **100.0% (300/300)** [98.7, 100.0] |
| crop 70% | 0.0% (0/300) | 100.0% (300/300) | **100.0% (300/300)** [98.7, 100.0] |
| rotate 10 deg | 21.0% (63/300) | 100.0% (300/300) | **100.0% (300/300)** [98.7, 100.0] |
| mirror | 0.0% (0/300) | 100.0% (300/300) | **100.0% (300/300)** [98.7, 100.0] |
| screenshot-like | 0.7% (2/300) | 99.0% (297/300) | **99.0% (297/300)** [97.1, 99.7] |

### False accepts (negatives)

| Negative class | n | pHash | Geometric | Pipeline (either) |
|---|---|---|---|---|
| Unrelated photo | 600 | 0.0% (0/600) | 0.0% (0/600) | **0.0% (0/600)** [0.0, 0.6], upper bound ~0.5% |
| Same person, different photo | 83 | 1.2% (1/83) | 1.2% (1/83) | **1.2% (1/83)** [0.2, 6.5] |

Closest unrelated pair: pHash distance 16/64 (limit 12); most geometric inliers on any
unrelated pair: 14 (limit 25).

### Exact SHA-256 binding (the browser verifier and `verify --image`)

0 of 3300 edited copies
were accepted as the original (upper bound 0.09%). This is by design: exact binding has
**zero tolerance**, so a re-encoded or screenshotted copy never matches the attested bytes. Near-copy matching is a
separate, weaker tool (pHash / geometric) with the error rates above.

### How to read this, and what it does not show

* pHash alone misses crops, rotations, mirrored copies and screenshot-like re-captures; the geometric test recovers
  them. On this data the combination catches every transformation tested at >= 99%, with no unrelated false accept in 600.
* This **replaces the earlier synthetic-only evidence** for the geometric verifier (docs/EVALUATION.md section 2b) with
  real photographs, but only of one kind: face-centred, 250 px, mostly frontal news photos.
* **Not measured:** phone photos, memes, screenshots of text or UI, logos, repeated textures (where geometric
  false matches are most likely), adversarially chosen negatives, large crops below 70%, stacked edits
  (crop + rotate + recompress), and heavily re-lit versions.
* The same-person hard negative has only 83 trials (few LFW identities have two photos among random picks), so its
  interval is wide. The single accept (`Mikhail_Kasyanov_0004` vs `_0003`, pHash distance 6, 31 geometric inliers) was
  inspected by eye: two frames of the same press event with near-identical framing, background and clothing. It is
  arguably a correct "related image" hit that the labelling scheme calls a negative, not a clear error. Treat the
  same-person rate as unmeasured at useful precision, not as 1.2%.
* This is a *provenance-of-the-image* test. Whether two photos show the same person is a different question
  measured in B1/B2 (and only on LFW).

## Not measured (do not claim)

* Anything outside the LFW-based labelled set of B7 (see its own list). Stacked edits and non-face content are the biggest gaps.
* Any demographic breakdown of face matching; IJB-C, CFP-FP, AgeDB; masks; age gaps.
* Any AI-image *detector*: none is implemented, on purpose (docs/DECISIONS.md D6). Only declared metadata signals exist and they are not scored.
* Real network download latency; CPU-only ArcFace latency.

## Rules

1. Report negative results.
2. A result changes status only after its command is run and the output is recorded here with date and hardware.
