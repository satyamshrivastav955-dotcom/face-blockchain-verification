# `tests/data/` — synthetic offline fixtures

These files let the full pipeline run with no network, no API key, no ONNX weights and no funded
wallet. They are **synthetic images, not photographs of anyone.** No face, real or generated, is
committed to this repository — `query.png` and `candidate_match.png` are smooth radial gradients, and
`candidate_other.png` is a stripe pattern. The stub face engine treats a whole image as one "face",
which is exactly why it is only ever a test harness.

| File | Role |
| --- | --- |
| `query.png` | Stands in for the input photograph. |
| `candidate_match.png` | A JPEG-round-tripped and rescaled copy of `query.png` — the candidate that should be **confirmed**. |
| `candidate_other.png` | An unrelated pattern — the candidate that should be **rejected**. |
| `candidates.json` | What a search provider would have returned. Relative `image_url` paths resolve against this directory. |

Run it:

```bash
python -m src.main register \
  --image tests/data/query.png \
  --fixture tests/data/candidates.json \
  --engine stub --allow-offline-stub \
  --dry-run --ascii
```

`--dry-run` substitutes a simulated local chain that persists to `localchain.json`, so
`verify` and `tamper-demo` work against it afterwards.

The rejected candidate is included on purpose: a fixture where everything matches proves only that
the code can say yes. The point of the confirmation stage is that it can also say no, and both
outcomes appear in the resulting score table.

## This is not a verification

The record produced this way is worthless as evidence and says so in three places: a warning banner
for the stub engine, another for the fixture provider, and `"offline_stub": true` inside the hashed
payload. Both the stub engine and the fixture provider refuse to run at all unless
`--allow-offline-stub` is passed explicitly, so a fake run cannot happen by accident or be mistaken
for a real one in a screenshot.

## Regenerating them

The generators live in `tests/conftest.py` (`make_blob`, `make_stripes`, `rewrite`, `write_png`), so
the fixtures and the unit tests share one definition. `make_blob`'s amplitudes are chosen so the
result never touches 0 or 255: a clipped image loses low-frequency structure when brightened, which
would break the perceptual-hash invariance tests for reasons that have nothing to do with the hash.
