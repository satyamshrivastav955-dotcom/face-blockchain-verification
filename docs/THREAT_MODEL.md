# Threat model

Scope: FaceProof as of v2.1 (this document tracks the code; see `docs/ROADMAP.md`). It covers the record
format, signing, anchoring (OpenTimestamps and the optional EVM registry), the C2PA bridge, the
client-side verifier, and the local pipeline. It is written to be attacked: every row names the control
that is meant to stop it, the test that exercises that control, and what is left over.

## 1. What is being protected, and the one claim

FaceProof makes one small, checkable claim:

> A file with SHA-256 *H* was described as *D*, by key *K* (optional), and the record of that description
> existed no later than time *T* (optional).

It never claims who is in an image, that an image is real, who made it, or when it was taken.

| Asset | Why it matters |
|---|---|
| The record (`payload`, `integrity`, `signature`, `anchor`) | A forged or altered record would misattribute or back-date evidence |
| The signing key (Ed25519, PEM file) | Whoever holds it can author records as you |
| The user's image and any face-derived data | Biometric/personal data; must not leak |
| The verifier page's integrity | A tampered page could lie about verdicts or exfiltrate files |

## 2. Actors

| Actor | Capability assumed |
|---|---|
| **Forger** | Edits records, re-seals them, replays someone else's record or signature |
| **Back-dater** | Tries to make a record look older than it is |
| **Stripper** | Removes or breaks C2PA manifests (screenshot, re-encode) |
| **Network adversary** | Controls or degrades calendar servers, block explorers, RPC nodes, search providers |
| **Hostile content host** | Serves malicious images/URLs the pipeline downloads (SSRF, decompression bombs) |
| **Malicious web host** | Serves a modified verifier page |
| **Curious analyst** | Holds a record or on-chain data and tries to learn faces or URLs from it |
| **Local attacker** | Reads files on the user's machine |

## 3. Attack matrix

| # | Attack | Control | Test | Residual risk |
|---|---|---|---|---|
| T1 | **Naive edit**: change a payload field, leave the hash | Hash is recomputed from the canonical payload (restricted RFC 8785 + SHA-256) in Python and in the browser | `tests/test_record.py`, `web/test/core.test.ts` ("any payload edit is caught offline") | None for in-profile payloads |
| T2 | **Re-sealed edit**: change a field and recompute the hash | Ed25519 signature covers the *hash*; a forger cannot sign the new hash. If unsigned, only the anchor catches it (the new hash was never stamped) | `tests/test_attest_and_signing.py::test_edited_payload_is_rejected_even_when_resealed...`, JS twin | An **unsigned, unanchored** record has no defence. Verification reports `NOT ANCHORED` (exit 3), never a pass |
| T3 | **Wrong signer**: a valid signature from some other key | `--trusted-key` / the page's "Require a specific signer" pins the expected key; a valid-but-unpinned signature is labelled "proves consistency, not identity" | `test_other_key_is_not_pinned`, `test_pinning_the_wrong_key_fails` | Key distribution is out of band. There is **no PKI, no revocation, no rotation** |
| T4 | **Signature replay**: attach an old signature to a forged record | The signature embeds the signed hash and is checked against the *recomputed* hash, not the stored field | `test_signature_bound_to_the_hash_not_the_stored_field` | None |
| T5 | **Wrong image**: present a different file with a genuine record | Image binding compares SHA-256 of the exact bytes | `test_wrong_image_is_rejected`, browser test | The binding is to *bytes*: a resized or re-encoded copy fails by design. Use pHash/derivative matching (CLI) for near-copies |
| T6 | **Verified without an image**: a pass that binds to nothing | Verdict text says "NOT bound to an image"; `--require-image` turns a missing image into *inconclusive*; the page warns | `test_require_image_is_inconclusive_without_one` | A user can still ignore the warning |
| T7 | **Back-dating**: claim an older time | OpenTimestamps proves the record hash existed by a Bitcoin block. Pending stamps are never a pass. EVM anchors prove block time | `tests/test_ots_anchor.py`, `test_ots_pending_is_not_success_and_confirmed_is` | The anchor proves the **record hash**, not when the **picture** was taken. Someone can attest an old photo today |
| T8 | **Calendar server lies or vanishes** | Verification needs only the proof + a Bitcoin header; submission goes to several calendars; a pending proof stays pending | `test_no_calendar_answering_is_an_error` | The public calendars are trusted for *liveness* of upgrades, not for correctness |
| T9 | **Block-header source lies** | Merkle path is recomputed locally; two explorers must agree; disagreement or silence -> *inconclusive*, never pass | `test_unreachable_explorer_is_inconclusive_not_fail`, JS explorer-agreement test | Both explorers could be compromised together. For full independence verify the `.ots` against your own node |
| T10 | **Hostile OTS proof** (oversized, deeply nested, unknown ops) | Size cap 64 KiB, depth cap 256, unsupported ops rejected, upgrade only contacts whitelisted calendar hosts (the URL inside a proof is untrusted) | `test_garbage_proof_is_a_fail_not_a_crash` | RIPEMD-160/SHA-1 steps are unsupported in the browser |
| T11 | **C2PA stripping** | Absence is reported as *absent* and described as proving nothing; the FaceProof record travels separately from the file | `test_stripping_the_manifest_is_silent_absence_not_a_pass` | A stripped file loses its embedded pointer. The record still works (hash binding) if the bytes are unchanged |
| T12 | **C2PA pixel edit after signing** | C2PA hard binding invalidates the manifest | `test_pixel_edit_after_signing_invalidates_the_manifest` | None beyond the C2PA spec's own limits |
| T13 | **Fake trust**: a self-made certificate looks official | Signers are `untrusted` unless their chain reaches a trust anchor *you* configured (`C2PA_TRUST_ANCHORS_FILE`). The project bundles and downloads no trust list | `test_self_made_certificate_is_untrusted_by_default`, `test_a_different_trust_anchor_does_not_trust_it` | Keeping the real C2PA Trust List current is the operator's job |
| T14 | **False AI label / missing AI label** | "Synthetic-media signals" are *declarations read from metadata*, flagged `is_detector: false`, `absence_proves_nothing: true`. There is no classifier | `test_png_generator_chunk_is_a_declaration`, `test_plain_image_has_no_declaration` | An attacker can add or remove a label. A label is evidence about a *claim* |
| T15 | **Verifier page exfiltrates files** | CSP `connect-src` allows only two block explorers; the page sends GETs only; a live "what this page sent" log; a browser test captures every request | `tests/test_verifier_browser.py` | A malicious *host* can serve a different page. Serve over HTTPS from a host you control, pin it with Subresource Integrity/your own build, or run `web/dist-verifier` locally |
| T16 | **Hostile image download (SSRF, DNS rebinding, bombs)** | IP-pinned, redirect-checked, size/pixel/time-bounded downloader | `tests/test_netguard.py` | Trusts the OS resolver |
| T17 | **Biometric leakage on-chain / in records** | Records hold no embedding; the face-match record stores a *commitment* only; attestation records contain **no face data and no filename**; chain data is hashes only | `test_payload_has_no_face_data_and_no_filename`, `tests/test_privacy_and_records.py` | A commitment is not anonymisation: whoever has the same embedding can confirm it. Treat face-match records as personal data |
| T18 | **URL commitment guessing** | `keccak256(url)` only | `tests/test_registry_evm.py` | Guessable URLs can be confirmed by brute force |
| T19 | **Key theft** | Key file created exclusively, mode 0600 where supported, never printed, git-ignored (`*.pem`, `*.key`) | `test_keygen_never_overwrites` | Keys are **unencrypted at rest**. Use disk encryption or a hardware key for anything important; there is no passphrase support yet |
| T20 | **Local web app exposed to a network** | Loopback bind, Host/Origin checks, upload limits | `tests/test_web_api.py` | **No authentication.** Do not expose it |

## 4. Trust assumptions, stated plainly

1. SHA-256, Ed25519 and Bitcoin proof-of-work are sound.
2. Your **verifier build** is the one you think it is. The browser page is only as trustworthy as the host that served it.
3. For OpenTimestamps, **at least one honest block explorer** (or your own node) supplies the real header.
4. For any "who signed this" statement, you obtained the **public key out of band**.
5. The operating system's random number generator is sound at key generation.

## 5. What FaceProof cannot defend against (do not claim otherwise)

* **Garbage in.** A record faithfully describes whatever file it was given, including a fake image.
* **Lying about identity or context.** A caption, a name or a "match" is the author's claim.
* **Perceptual-hash collisions** and adversarial near-duplicates when using pHash/geometric matching.
  See `BENCHMARKS.md` for measured error rates and their limits.
* **AI-image detection.** There is no detector; published 2026 benchmarks show open detectors failing on new
  generators and under compression (docs/DECISIONS.md D6).
* **Coerced or compromised signers**, and **rubber-hose** attacks on the key holder.
* **Metadata privacy of the timestamp request.** Calendars see the record hash and your IP address.
* **Legal admissibility.** Nothing here is legal advice or a legal standard of proof.

## 6. Reviewer's list of the weakest points

1. Unencrypted private key at rest; no key rotation or revocation.
2. Block headers come from public explorers by default.
3. The first-party verifier page is trust-on-first-use.
4. Face-match records are personal data even though no embedding is stored.
5. EVM registry anchors cannot be checked in the browser.
6. The perceptual hash is not implemented in the browser: it verifies exact bytes only.
