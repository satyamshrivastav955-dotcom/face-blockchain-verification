# Evaluation methodology and what has (and has not) been measured

Thresholds are **not universal constants**. The cosine cut-off (default 0.363) is the value OpenCV
documents for SFace in its own example; it depends on the model, the data, image conditions and how
"same" is defined, and it carries no guarantee for your images. The pHash cut-off (default 12/64) is a
project default, not a standard. Nothing here establishes accuracy for any population, and **no
demographic-fairness claim is made or supportable** from this repository.

## 1. Image-derivative (pHash) test — measured on synthetic images only

Reproduce:

```bash
python scripts/evaluate_phash.py --threshold 12 --images 40
```

Environment of the run recorded below: Python 3.13.13, OpenCV 5.0.0, NumPy 2.2.6, Windows 11. Fixed
seeds; no network. **Synthetic smooth random fields, not photographs** — they have different frequency
statistics from real photos, so these numbers demonstrate the mechanism, not real-world performance.

```
transformation     pairs  min   med  max   TA   FR
resize 50%            40    0   0.0    6   40    0
resize 25%            40    0   2.0    8   40    0
jpeg q80              40    0   2.0    6   40    0
jpeg q50              40    0   2.0    6   40    0
jpeg q20              40    0   4.0   10   40    0
blur sigma 1.5        40    0   0.0    4   40    0
blur sigma 4          40    0   0.0    8   40    0
brightness +30        40    0   0.0   10   40    0
centre crop 90%       40    4  10.0   20   31    9
centre crop 70%       40   16  24.0   36    0   40
rotate 5 deg          40    2   8.0   14   37    3
horizontal flip       40   28  32.0   34    0   40

unrelated pairs: 780  distance min/median/max = 16/32.0/44  false accepts 0  true rejects 780
```

(TA = true accept, FR = false reject: the same image transformed, distance <= 12.)

What this does show: the pHash test tolerates rescaling, recompression, blur and brightness changes on
this synthetic set, and misses heavier crops (70%) and mirrored copies — which is exactly the gap the face
test exists to cover, and why a pHash-only success is labelled an *image-derivative* match. Unrelated
synthetic pairs were all far from the threshold (min 16), but 40 images is a tiny sample.

## 2. Face-match test — measured on LFW (public research dataset)

Reproduce (weights and data are git-ignored; weights are non-commercial research only):

```bash
python scripts/fetch_models.py && python scripts/fetch_insightface.py
python scripts/benchmark_face.py --engines opencv,arcface-r50,arcface-r100 --json out.json
```

The raw results of the run below are in [`docs/results/lfw_benchmark.json`](results/lfw_benchmark.json).

**Protocol.** LFW image-restricted 10-fold protocol: 6,000 pairs (3,000 same / 3,000 different) from `pairs.txt`,
the 7,701 *raw, unaligned* images going through the full production path (detect, align, embed). The pair score is
the cosine of the selected subject faces. Detection failures are scored as a forced reject and counted, never
dropped. Accuracy is 10-fold cross-validated (threshold fit on 9 folds). TAR at FAR is computed on all pairs; with
3,000 negatives **FAR = 1e-3 means 3 false accepts**, so read it as indicative.

Environment: Python 3.13.13, OpenCV 5.0.0, ONNX Runtime 1.23.2, Windows 11, Intel CPU, **NVIDIA RTX 4050 Laptop GPU
(6 GB)**. ArcFace engines ran on the CUDA provider; SFace runs on CPU (OpenCV DNN).

| | SFace (OpenCV, MIT/Apache) | ArcFace-R50 | ArcFace-R100 |
|---|---|---|---|
| 10-fold accuracy | 99.32% ± 0.36 | **99.65% ± 0.29** | 99.63% ± 0.29 |
| EER | 0.83% | **0.60%** | 0.67% |
| TAR @ FAR 1e-2 | 99.23% | **99.40%** | 99.33% |
| TAR @ FAR 1e-3 | 98.47% | **99.33%** | 99.30% |
| Threshold at FAR 1e-3 | 0.359 | 0.221 | 0.251 |
| Images with no face found | 0 / 7,701 | 2 | 2 |
| Latency, 250 px image (p50) | 32 ms (CPU) | 23 ms (GPU) | 26 ms (GPU) |
| Latency, 1280 px image (p50) | 169 ms (CPU) | 22 ms (GPU) | 26 ms (GPU) |

Notes that matter:

* **LFW is saturated.** Every engine is above 99%, so clean accuracy barely separates them, and R100 is not better
  than R50 here (it may be on harder data; that is unmeasured). The differences that are clearly outside noise are in
  the stress tests below and in TAR at FAR 1e-3.
* SFace's own documented threshold (0.363) lands almost exactly on its FAR-1e-3 point (0.359): an independent
  sanity check of that number, on this data.
* The defaults for the ArcFace engines (0.25 / 0.28) are the FAR-1e-3 thresholds plus a ~0.03 margin. They are
  indicative, not calibrated for any population.
* The AUC column is deliberately not in the table: the three forced-reject pairs from ArcFace's two missed images
  depress its AUC (0.9969 vs SFace 0.9987) even though its accuracy and EER are better. Using the centre-face rule
  instead of the production rule, ArcFace-R50's AUC is 0.9981 and EER 0.40%.
* **GPU vs CPU is not a like-for-like model comparison.** ArcFace's latency is flat in image size because detection
  runs on a fixed 640x640 canvas on the GPU; SFace on this CPU scales with image size. On a CPU-only machine the
  ArcFace engines will be slower; that was not measured.

### Stress tests (second image of 600 balanced pairs degraded; clean-fit threshold; accuracy / failure to enroll)

| Degradation | SFace | ArcFace-R50 | ArcFace-R100 |
|---|---|---|---|
| downscale 5x | 94.3% / 0.3% | **99.5%** / 0% | 99.3% / 0% |
| JPEG quality 12 | 98.7% | 99.7% | 99.5% |
| Gaussian blur sigma 3 | 98.3% | 99.3% | 99.3% |
| low light (x0.3) | 99.2% | 99.5% | 99.5% |
| lower-face occlusion band | 97.7% | 99.2% | 99.0% |
| rotate 30 degrees | **90.2%** | **99.7%** | 99.5% |

This is where the newer models earn their place: rotation and tiny faces cost SFace 5–10 points and ArcFace almost
nothing. Each cell is 600 pairs, so differences of about one point are within noise.

### Subject-face selection (a finding, not a tuning)

SCRFD detects more than one face in 1,527 of 7,701 images (about 20%). Scoring the *largest* face instead of the
subject costs ArcFace-R50 2.4 points (97.3% vs 99.7% accuracy) and SFace 0.4. The pipeline therefore ranks faces by
prominence (size weighted by centrality); it is within 0.1 point of the oracle centre rule on LFW's centred
subjects, and it warns when a second face is comparably prominent. It will still be wrong for a photo whose subject
is small and off-centre among larger bystanders — crop such photos.

### Still not measured

IJB-C, CFP-FP, AgeDB, masks/occlusion datasets, age gaps, and any demographic breakdown: not available here. No
fairness claim is made. LFW is not demographically balanced. Cross-machine score variability was not measured
(one machine). The InsightFace weights are **non-commercial research only**.

## 2b. Geometric verification (SIFT + RANSAC) — measured on synthetic images only

On textured synthetic images (`tests/test_geometry.py`) derivatives yielded 46–309 inliers (crops down to 40%,
rotation, mirroring, JPEG q15, blur, an overlay) against at most 7 for unrelated images, with thresholds at 25
inliers and ratio 0.30. That is a mechanism check: **real photographs have repeated structure (text, logos,
facades) that can produce spurious matches, and this has not been measured on real-image negatives.**

## 2c. Other measurements

| Measurement | Result |
|---|---|
| Candidate downloads, 8 candidates at simulated 150 ms latency | 1 worker 1.21 s; 2: 0.61 s; 4: 0.31 s; 8: 0.17 s (near-linear; simulated latency, not real network) |
| Anchoring gas (in-process EVM, solc 0.8.24, optimiser 200) | single record 74,464; Merkle batch of 1: 74,174; batch of 1,000: 74,186, i.e. **~74 gas per record at N=1,000** (about 1,000x less than one transaction each). Gas on a real chain also depends on calldata pricing and L1 data fees on L2s, which this does not model |

## 3. Real-model checks that *were* run (`tests/test_real_models.py`, needs `models/`)

Model integrity (pinned SHA-256 and size), loading, SFace output shape/finiteness/determinism on a
synthetic 112x112 input, and the no-face and degenerate-input paths of YuNet. These are correctness checks,
not accuracy measurements.

## 4. Timings (single machine, single run of the command shown — not a benchmark)

Environment: Python 3.13.13, OpenCV 5.0.0, Windows 11, Intel CPU (family 6 model 191), CPU inference.

| Measurement | Result |
|---|---|
| Model initialisation (load YuNet + SFace) | 132 ms |
| YuNet `detect` on a 640x480 synthetic image with no face, median of 20 | 9.9 ms (min 8.8, max 13.9) |
| SFace `feature()` on a 112x112 input, median of 20 | 5.8 ms |
| Offline stub `register` with 2 local candidates, whole process incl. interpreter start | 1.30 s |
| Full test suite (578 tests, incl. in-process EVM, web API, real-model checks) | 32 s |
| `scripts/evaluate_phash.py` (40 images, 12 transforms) | 0.66 s |

The detection time is for an image without a face, so it excludes alignment and embedding. No candidate
**download** timing is reported: downloads were only exercised against scripted offline fakes, which say
nothing about real network latency. No memory profile was taken; decoded-image memory is *bounded* by
limits (<= 16384 px per side, <= 50 MP, <= 25 MiB download) rather than measured.
