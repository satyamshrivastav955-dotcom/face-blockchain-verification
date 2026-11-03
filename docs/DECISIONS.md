# Decisions

Format: date, decision, why, alternatives, status. Newest last. Entries before 2026-11-02 are reconstructed from
the repo history (`CHANGELOG.md`, `docs/PIPELINE.md`) and marked *inherited*.

## Inherited (pre-audit)

* **Evidence labels: "face match" vs "image derivative", never merged.** Prevents overstating image similarity as identity.
* **Restricted RFC 8785 canonicalisation, named as such.** Floats rejected; honest label beats a false "JCS" claim.
* **Fail-closed verification, exit code 6 = inconclusive.** An unreachable chain is never a pass.
* **Only `keccak256(url)` goes on-chain, never face data.**
* **Merkle batching (RFC 6962) for anchoring.** Amortises gas; leaf binds the URL commitment.
* **Default engine stays permissive (OpenCV YuNet+SFace); InsightFace weights opt-in** because they are non-commercial research only.

## 2026-11-02: Phase 0 (reproducibility)

* **Split EVM test extras into `requirements-evm.txt`.** `eth-tester[py-evm]` -> `safe-pysha3` fails to build on Windows (verified), which broke
  `pip install -r requirements-dev.txt` entirely and left the project's `.venv` half-installed. Dev install is now pure wheels.
  Cost: contract tests silently skip locally; mitigated by a CI step that fails if they skip.
* **README test-count claim qualified.** Re-run: Windows 665 passed/1 skipped; Ubuntu+EVM 688 passed/7 skipped of 695 collected. 695 passing requires the git-ignored C2PA sample and `node`. Also found: `constraints.txt` (resolved on 3.13) does not install on Python 3.14; use 3.13 until re-resolved.
* **`.req-tmp.txt` and `*.mp4` git-ignored.** The untracked 130 MB recording must not be committed by accident. Nothing deleted.

## 2026-11-03: decisions taken while executing the approved roadmap

The owner asked for the whole plan to be executed in one pass. The five open questions of 2026-11-02 were answered
with the recommendations below. Each is reversible and each is the owner's to overturn.

### D1. Anchoring: OpenTimestamps is the recommended backend; the EVM registry stays as an option

* **Chosen:** `--anchor ots` (Bitcoin via OpenTimestamps) added and recommended; `--anchor chain` stays the default of
  `register` for backward compatibility; `attest` defaults to `none` (fully offline).
* **Why:** an anchor can only prove "this hash existed by time T". OpenTimestamps proves exactly that with no wallet,
  no gas, no contract to deploy or trust and no testnet whose lifetime is uncertain (Ethereum announced end of support
  for Sepolia on 2026-09-30; the effect on Base Sepolia was not confirmed). Verification is a Merkle path plus one
  Bitcoin header; the proof file is independent of this project.
* **Why the default was not flipped:** `register` writing to a network by default would send data to third parties
  without consent and break every existing record and test. Flipping the default is a v3 decision.
* **Alternatives considered:**
  * *Sigstore Rekor v2* (GA, tile-based, no gas). A transparency log with inclusion proofs; built for software-signing
    entries, and I did not confirm that the public instance accepts arbitrary image-record entries. It also returns no
    signed timestamp itself (a separate timestamp service is needed). **Not implemented**; the Merkle code here is
    already RFC 6962-shaped, so a Rekor backend would be a thin adapter if the log accepts the entry type.
  * *EAS on a mainnet L2 (Base).* Adds attester identity and schemas, at the price of a gas wallet, an operator and a
    per-record fee (secondary sources put Base transfers at roughly $0.001-$0.02; not measured by me). Worth it only if a
    verifier needs an on-chain attester identity, which the Ed25519 signature already provides off-chain.
  * *Keep the self-deployed contract.* Fine as a demo; a testnet registry is not a product. It remains selectable.
* **Partly verified live:** with the owner's approval, one record hash was submitted on 2026-11-03 and accepted by all three
  public calendars; verification reports it pending, as it must. The Bitcoin confirmation and the upgrade step are still
  unobserved, and the header check has only been exercised against a fabricated header.

### D2. The one-to-many search stays, but is opt-in, secondary, and separated from the core

* **Chosen:** the product's centre is `attest` + the verifier, which never process a face. The search-and-face-match
  "trace" flow remains behind per-provider consent flags and is labelled as the only face-analysing part (UI, README,
  `docs/PRIVACY.md`).
* **Why:** removing it deletes a working, tested, measured feature; keeping it as the default contradicts "never
  identification". Making it explicit and optional is the honest middle.
* **Residual risk:** a reviewer can still say a face-similarity search over provider results is face recognition.
  It produces a similarity measurement and never names anyone, but it is biometric processing of third parties' images.

### D3. LICENSE: not added

Owner's decision. The InsightFace weights are non-commercial, which constrains any licence for a combined work.

### D4. `assets/demo_*.png`: left in place

They show third parties' photographs from public posts (the README already warns). Deleting files needs the owner.

### D5. Node and browser tooling: approved implicitly by "complete the plan"

`node --test` (Node >= 24, no extra package) runs the verifier tests. Playwright (Python) drives an installed
Chrome/Edge; no browser download.

### D6. No AI-image detector

* **Chosen:** "synthetic-media signals" are *declarations read from the file* (C2PA `digitalSourceType`, XMP
  `DigitalSourceType`, generator chunks written by local tools). They are labelled `is_detector: false` and
  `absence_proves_nothing: true`.
* **Why:** 2026 benchmarks report open detectors failing on newer generators and collapsing under compression (e.g.
  one study found 18-30% average accuracy on current commercial generators; NTIRE 2026 reports a large
  clean-vs-distorted robustness gap). Shipping one would require publishing error rates that I could not honestly make
  look good, and downloading third-party weights I could not vet. Google's SynthID Detector (public 2026-10-07)
  only recognises media from adopting vendors and has no local path, so it cannot be a private signal.
* **Revisit if:** a detector with a measured, published error rate on a held-out, recompressed set can be added behind a
  flag, with its failure cases printed next to its score.

### D7. The browser verifier does exact-byte binding only; no ONNX, no face model, no pHash

* **Why:** the wedge says the verifier never identifies anyone; shipping a face model into the verification page would
  contradict that and add a large attack surface. pHash in JS would have to match OpenCV's DCT bit-for-bit, which is
  unproven. Near-copy matching stays in the CLI.
* **Brief said:** "WASM/ONNX Runtime Web". Not done, deliberately; documented here so it is not mistaken for an omission.

### D8. Signatures: Ed25519 over the record hash, key pinned out of band

* **Why:** the hash proves consistency, not authorship. Ed25519 is in WebCrypto (Chrome 137+, Firefox, Safari), so the
  verifier needs no library. Domain-separated message (`faceproof-record-v1\0` + hash).
* **Not done:** key rotation, revocation, passphrase-protected keys, transparency for keys. Listed in THREAT_MODEL.md.

### D9. C2PA: write a pointer, read with trust anchors you supply

* **Why:** C2PA already solves hard-binding signed provenance for cameras and tools. FaceProof embeds only a reference
  (`org.faceproof.record`) and reads Content Credentials. Trust: no trust list is bundled or downloaded; pass your own
  anchors (`C2PA_TRUST_ANCHORS_FILE`). A self-made certificate is reported *untrusted*.
* **Known limit:** embedding changes the file bytes, so the embedded file's SHA-256 differs from the one in the record.
* **Not done:** reading C2PA in the browser (`@contentauth/c2pa-web` was not evaluated: bundle size, licence, and its
  default network calls for trust/CAWG checks were not verified).
