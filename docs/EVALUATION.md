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

## 2. Face-match test — NOT evaluated

Measuring YuNet + SFace honestly (true/false accepts and rejects, failure-to-detect rate, behaviour under
size, compression, blur, crops and multiple faces) needs a **licensed, consented face dataset with identity
labels**. The repository ships none (`tests/data/` is synthetic, by design) and no dataset was downloaded.
Therefore:

* no confusion matrix, accuracy, false-accept/false-reject rate or failure-to-detect rate is reported for
  the face test;
* no cross-platform variability of embeddings was measured (only one environment was available);
* the existing README screenshots show individual runs, not an evaluation.

If you build an evaluation set, keep it outside Git, record licences and consent, report counts rather
than percentages when samples are small, and keep results out of the regression tests.

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
