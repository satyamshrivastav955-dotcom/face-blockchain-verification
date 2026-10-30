# Security policy

## Scope and status

FaceProof is an image-provenance tool. It is a research/portfolio project: it has **not** had an
independent security audit, the registry contract has **not** been deployed, and the local web app has
**no authentication** and must not be exposed to a network.

## Reporting a vulnerability

Please report privately rather than in a public issue. Use GitHub's private vulnerability reporting for
this repository (Security tab → "Report a vulnerability"), or contact the maintainer through the address on
their GitHub profile. Include a description, steps to reproduce, affected files or commands, and the impact
you expect. Please do not include real personal photographs or secrets in a report.

You can expect an acknowledgement, and a fix or a documented decision, as the maintainer's time allows; there
is no service-level commitment.

## What is in scope

* The SSRF guard and image-decoding limits (`src/vision/netguard.py`, `src/vision/preprocess.py`)
* Consent gates and secret redaction (`src/privacy.py`, `src/main.py`, provider modules)
* Record, canonicalization and bundle integrity (`src/evidence/`)
* The registry contract and its client (`contracts/`, `src/blockchain/`)
* The local web API (`src/web/`): host/origin checks, upload handling, temp-file lifecycle

## What is out of scope

* Weaknesses of third-party services (search providers, RPC nodes, public image hosts) or of the
  non-commercial InsightFace weights
* Face-recognition accuracy, bias or demographic performance: see `docs/EVALUATION.md` for what was and was
  not measured
* Anything requiring the web app to be deliberately exposed beyond loopback

## Handling secrets

Never commit `.env`, private keys or API keys. Use a burner wallet funded from a testnet faucet for any
deployment. `doctor` and all error paths are designed never to print secret values; a violation of that is a
reportable bug.
