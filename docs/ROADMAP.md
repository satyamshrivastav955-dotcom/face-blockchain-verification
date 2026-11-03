# Roadmap and state

Last updated: 2026-11-03. Everything below is uncommitted in the working tree; nothing was pushed or deployed.

## Verified state

* Python: ruff, ruff-format and mypy clean. Test suite results are recorded in `BENCHMARKS.md` (B6, B8, B9).
* Image-only `attest` (no face, no network by default), Ed25519 signing, OpenTimestamps anchoring, C2PA write + trust-anchor
  read, declared synthetic-media signals, browser verifier (13 cross-checked unit tests + 4 real-browser tests),
  six-forgery tamper suite, labelled evaluation on real photographs.
* Docs: THREAT_MODEL, PRIVACY, DECISIONS, BENCHMARKS, INTERVIEW_PACK.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 0 | Reproducible install, living docs, hygiene | Done |
| 1 | Threat model, privacy and legal posture | Done (DPDP summary is from secondary sources) |
| 2 | Anchor backend (OpenTimestamps), signed records, image binding flags | Done; **live calendar submission not exercised** |
| 3 | C2PA write, trust-anchor-aware read | Done; browser-side C2PA not done |
| 4 | Static client-side verifier | Done; EVM anchors and pHash not checkable in-page (by design) |
| 5 | Labelled evaluation with confidence intervals | Done (LFW-based; see limits in BENCHMARKS.md B7) |
| 6 | Synthetic-media signal | Done as declared-metadata only; **no ML detector, by decision D6** |
| 7 | Tamper demo, containers, CI | Demo done; both images built and smoke-tested 2026-11-03 (one real bug found and fixed); CI edited but **never run on GitHub** |
| 8 | Interview pack | Done (`docs/INTERVIEW_PACK.md`) |

## Not done, in priority order

1. Run CI on GitHub (needs a push, which only the owner does) and fix whatever breaks.
2. Finish the OpenTimestamps round trip: a stamp was submitted on 2026-11-03 (`docs/examples/live-ots-attestation.json`, status pending).
   After a few hours run `python -m src.main ots-upgrade --record docs/examples/live-ots-attestation.json`, then `verify` with the image
   `tests/data/query.png`. Expected: `VERIFIED ... TIMESTAMPED ON BITCOIN`. If it does not, that is a bug to fix.
3. Deploy the static verifier (`web/dist-verifier`) behind HTTPS on a host you control; add Subresource Integrity or a
   signed release so users can check the page is the one you built.
4. Passphrase-protected or hardware-backed signing keys; key rotation and revocation.
5. Stacked-edit, phone-photo, screenshot-of-UI and repeated-texture evaluation; per-demographic face-match evaluation.
6. Evaluate a Rekor v2 backend if the public log accepts the entry type; evaluate EAS if on-chain attester identity is needed.
7. Browser-side C2PA reading (`@contentauth/c2pa-web`): check licence, size and default network behaviour first.
8. LICENSE and the third-party photos in `assets/` (owner's decisions, D3/D4).
9. Flip the default anchor to OpenTimestamps in a major version.
