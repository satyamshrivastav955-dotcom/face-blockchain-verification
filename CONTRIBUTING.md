# Contributing

## Set up

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
make install-dev            # or: pip install -r requirements-dev.txt -c constraints.txt
make models                 # optional: real model weights (needed only by tests/test_real_models.py)
(cd web && npm ci)          # only for the frontend
```

`make help` lists every target. `make check` runs what CI runs for Python: ruff, ruff format, mypy and the
hermetic test suite (no network, keys, wallet or gas). The contract tests need `eth-tester[py-evm]` and skip,
with a reason, when it is missing.

## Principles that review will hold you to

1. **Nothing fabricated.** No invented benchmark numbers, example scores, transaction hashes or "sample" data
   presented as real. Anything simulated or test-only is labelled as such in code, output and records.
   Numbers in docs come from a command that is named next to them.
2. **Fail closed.** A check that could not run is *inconclusive*, never a pass. Technical failures are not
   negative results.
3. **Distinguish kinds of evidence.** A face match, an image-derivative match and a C2PA state are different
   claims and are worded differently everywhere.
4. **Privacy by default.** Nothing leaves the machine without an explicit consent flag that names what is
   sent. No embeddings, face crops or plaintext URLs on-chain or in logs. No secrets in output.
5. **Test behaviour, not strings.** Add a regression test with every fix; prefer running the code (including
   the in-process EVM) over asserting that source text exists.
6. **Say what was not measured.** Limits belong next to the claim.

## Style

* `ruff format` and `ruff check` (rules E, F, W, B, I, UP) must be clean; `mypy` must pass.
* Match the surrounding code's comment density and naming. Comments explain *why*, not what.
* Keep the CLI entry point `python -m src.main` stable; new exit codes need documenting in the README,
  `src/main.py` and `docs/`.
* Do not commit models, datasets, `.env`, generated records or evidence (`.gitignore` covers them).

## Licensing

The repository has no `LICENSE` file yet; contributions are accepted on the understanding that the owner will
choose one. InsightFace weights are non-commercial research only: never add or redistribute them.
