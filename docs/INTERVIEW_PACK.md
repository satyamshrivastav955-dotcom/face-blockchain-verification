# Interview pack

Every number below is in `BENCHMARKS.md` with the command that reproduces it. Where something is not done, the
answer says so; do not claim past this page.

## 1. The two-minute pitch

> FaceProof answers a narrow question: *is this record genuine, and is this the file it describes?* — without
> trusting me, and without ever claiming to know who is in a picture.
>
> You run `attest` on an image. It writes a small JSON record: the file's SHA-256, a perceptual hash, whether it
> carries C2PA Content Credentials, and any generative-AI label in its metadata. It does **not** detect a face. You
> sign it with an Ed25519 key, and optionally timestamp the record hash on Bitcoin through OpenTimestamps — no
> wallet, no gas. Anyone can then drop the record and the image on a static web page that runs entirely in their
> browser: it recomputes the hash, checks the signature, checks the exact bytes, and verifies the Bitcoin proof. A
> content-security policy means the page physically can't send the files anywhere, and it shows every request it
> makes.
>
> I started from a project that put face-match hashes on a testnet contract. I challenged that: a registry can only
> prove "this hash existed by time T", and OpenTimestamps proves that for free, so the contract became optional. I
> also cut scope on purpose — there is no AI-image detector, because the published 2026 benchmarks show open
> detectors failing on new generators and under compression, and I couldn't give you an honest error rate.
>
> What I can show: a six-forgery tamper demo that exits non-zero if any forgery is accepted; cross-checked
> Python/JavaScript verifiers; and error rates on real photographs — a near-copy test that caught every one of 12
> kinds of edit (≥99%) while accepting 0 of 600 unrelated photos, with the caveat that it's only been measured on
> face-centred 250-pixel news photos. What's not done: a live OpenTimestamps run, the Docker builds and CI, and any
> demographic evaluation of the face matcher.

## 2. Architecture to draw on a whiteboard

```
                  YOU (offline)                                      ANYONE (browser, no server)
 ┌────────────┐   attest    ┌──────────────────────────┐          ┌─────────────────────────────┐
 │  image.jpg │ ──────────► │ payload (hashed)          │          │ static page  (CSP: only      │
 └────────────┘             │  source_image{sha256,     │          │ blockstream/mempool GETs)    │
                            │   pHash, size, C2PA state}│  record  │  1. canonicalise + SHA-256   │
 ┌────────────┐   sign      │  synthetic_media_signals* │ ───────► │  2. Ed25519 verify (+ pin)   │
 │ Ed25519 key│ ──────────► │  claim, limitations       │  + image │  3. SHA-256(image) == record │
 └────────────┘             ├──────────────────────────┤          │  4. OTS proof -> Bitcoin hdr │
                            │ integrity: sha256(JCS)    │          └─────────────────────────────┘
                            │ signature: ed25519(hash)  │                       ▲ header only
                            │ anchor: OTS proof ────────┼── hash only ──► calendars ──► Bitcoin
                            └──────────────────────────┘
   * declared in metadata, never "detected";  no face, no filename anywhere in this record

 Optional, consent-gated "trace" branch (the only part that touches a face):
   image ─► local face model ─► reverse-search provider (consent flag) ─► SSRF-guarded download
         ─► re-check each lead locally (face cosine | pHash | SIFT+RANSAC) ─► face-match record ─► EVM/OTS anchor
```

Draw in this order: (1) the file, (2) the record with the *three separate proofs* — hash (consistency), signature
(author), anchor (time) — (3) the arrow to the browser, (4) the dotted "trace" branch, labelled "only this analyses a
face". The thing to say while drawing: **each proof is checked and reported separately, and a missing one is never a pass.**

## 3. Fifteen hard questions

**1. Why did you move away from the blockchain registry?**
A chain anchor proves one thing: this hash existed by block time T. OpenTimestamps proves the same thing against
Bitcoin with no wallet, no gas, no contract to deploy or trust, and no testnet to be retired (Ethereum announced end
of Sepolia support on 2026-09-30; I couldn't confirm what that means for Base Sepolia). The contract is still there as
`--anchor chain`; I just no longer call it the design. EAS on an L2 would be justified only if a verifier needs an
on-chain attester identity — and the Ed25519 signature already provides that off-chain.

**2. What does a "verified" result actually prove?**
That the record is unchanged since it was sealed; that a specific key signed it (and, if you pinned that key, that
it's the key you expected); that the file you hold is byte-for-byte the one described; and that the record hash
existed by a Bitcoin block. It proves nothing about whether the image is real, who made it, when it was taken, or who
is in it. The page says that under every result.

**3. Someone re-seals a forged record. What stops them?**
If it's signed: the signature covers the hash, so a new hash needs the key — tested in Python and in the browser. If
it's unsigned and unanchored: nothing, and the verifier says so (`NOT ANCHORED`, exit 3) rather than passing. That's a
real limit: an unsigned, unanchored record is just a file.

**4. A signature from an unknown key — is that trustworthy?**
No. A valid unpinned signature proves *a* key signed it. Identity is a policy decision made by pinning the author's
public key out of band, and the UI and CLI label an unpinned pass "proves consistency, not identity". There is no PKI,
rotation or revocation; that's listed as a weak point.

**5. Can I back-date a record?**
You can attest an old photo today, and the anchor will honestly say *today*. What you can't do is make the record
claim an earlier anchor time. The anchor proves the hash's age, not the picture's.

**6. Why should I trust the verifier page?**
Only as much as the host that served it. Mitigations: tiny dependency-free script (about 15 KB), a CSP whose
`connect-src` allows two block explorers and nothing else, a visible request log, and a Playwright test that captures
every request and asserts no body and no unexpected host. The residual risk is a malicious host serving a different
page; the answers are self-hosting, running `dist-verifier` locally, and (not done yet) Subresource Integrity or a signed
release.

**7. You trust public block explorers for the Bitcoin header. Isn't that a hole?**
It's a stated assumption. The Merkle path is recomputed locally, two explorers must agree, and disagreement or silence
is *inconclusive*, never a pass. For full independence you verify the same `.ots` with your own node. I would not call
the browser check trustless.

**8. What failed or surprised you?**
Three things. (a) The cross-implementation test caught a real bug on day one: my JavaScript verifier reported "verified"
when you pinned the *wrong* signing key, because it treated "valid signature" as a pass before checking the pin. The
Python reference failed correctly; the shared vectors exposed it. (b) The repo's own claim of 695 passing tests only held
when two optional inputs were present; on a clean checkout it's 688 + 7 skips, and the dev install didn't work on Windows
at all (a C-extension dependency). (c) In my labelled evaluation, the one "false accept" among same-person negatives turned
out to be two near-identical frames from one press event — my labelling scheme, not the matcher, was arguably wrong.

**9. What are the limits of your error rates?**
They're measured on 300 LFW source photos: face-centred, 250 px, mostly frontal news photos. Recall on 12 edits is ≥99%
each; 0 of 600 unrelated photos were accepted (95% upper bound ≈0.5%). Not measured: phone photos, screenshots of
text/UI, logos, repeated textures (where SIFT false matches are likeliest), stacked edits, adversarial negatives. The
same-person hard-negative class has only 83 trials, so its rate is unmeasured at useful precision.

**10. Why is there no AI-image detector? Isn't that a gap?**
It's a decision. 2026 benchmarks report open detectors at 18–30% average accuracy on newer commercial generators and
large drops under compression (NTIRE 2026 documents the clean-vs-robust gap). Shipping one means publishing an error
rate I can't make honest, and downloading weights I can't vet. What exists are *declared* signals (C2PA/XMP source type,
generator chunks), labelled `is_detector: false`, and their absence is explicitly "proves nothing". SynthID's public
detector (Oct 2026) only recognises partner-generated media and has no local path, so it can't be a private signal either.

**11. Is the face search just facial recognition with extra steps?**
The honest answer: the *trace* mode runs a face model against images a search provider returns, which is one-to-many
biometric processing of third parties' photos, even though it outputs a similarity score and never a name. That's why it
was demoted: off by default, per-provider consent flags, the disclosure printed before anything is sent, and the product's
core (`attest`, the verifier) processes no face at all. A reviewer can still object to the trace mode, and I wouldn't argue
that it's risk-free.

**12. What would a security reviewer find first?**
Unencrypted signing keys at rest; no rotation/revocation; the first-party verifier page being trust-on-first-use;
block headers from public explorers; the local web app having no authentication (documented, loopback-only). All are
in `docs/THREAT_MODEL.md` section 6 along with the control and test for each of the 20 attack rows.

**13. How do you know the browser and Python verifiers agree?**
Python generates test vectors (canonical bytes for tricky Unicode and escaping, a signed record, a pending proof, a
Bitcoin-attested proof against a fabricated header); 13 Node tests assert the same verdicts and bytes. And because
canonicalization is a *restricted* RFC 8785 profile — floats and >2^53 integers rejected — the browser can't silently
differ on number formatting. The bug in question 8(a) is exactly what this setup is for.

**14. What is C2PA's role, and why not just use C2PA?**
C2PA solves signed, hard-bound provenance for cameras and editing tools, and I read it and can embed a pointer to a
record. But a manifest vanishes when a screenshot or platform re-encodes the file, and most images don't have one. The
FaceProof record is separate from the pixels, so it survives that — at the price of binding to exact bytes. I don't bundle a
trust list, so a self-made certificate is reported *untrusted*; the official C2PA Trust List and conformance program are
the real trust mechanism and I didn't build a substitute.

**15. What would you change next?**
In order: run the unverified things (a live OpenTimestamps round trip, the Docker builds, CI on GitHub); host the verifier
with SRI or a signed release; passphrase- or hardware-backed keys with rotation; evaluate phone photos, UI screenshots and
stacked edits; per-group evaluation of the face matcher before anyone trusts it for more than a demo; and flip the default
anchor to OpenTimestamps in a major version. I'd also reconsider whether the trace mode should live in this repo at all.

## 4. Three resume bullets (each number is reproducible; see BENCHMARKS.md)

* Re-architected an image-provenance tool around an offline, face-free signed record (Ed25519 + RFC 8785 hashing) with
  OpenTimestamps Bitcoin anchoring, replacing a testnet-contract dependency; built a 15 KB dependency-free browser verifier
  with a CSP-enforced no-upload guarantee, cross-checked against the Python reference by 13 shared-vector tests (which caught
  a pinning bug) and 4 real-browser tests.
* Measured a near-copy matcher on 300 real photographs (3,600 transformed copies including 300 identical, 683 negatives, Wilson intervals): ≥99% recall on
  all 12 edits including crops, rotations, mirroring and screenshot re-captures, 0/600 unrelated false accepts (≤0.5% at 95%);
  documented what the data does not cover instead of rounding it up.
* Wrote a 20-row threat model and a six-forgery tamper suite (exit non-zero if any forgery is accepted), and made scope calls on
  evidence: dropped an AI-image detector after benchmark review, demoted one-to-many face search to an opt-in path, and corrected
  an inherited test-count claim after reproducing it on Windows and Linux.

(If an interviewer asks for the test count: 688 passed / 7 skipped on Linux for the pre-existing suite; see BENCHMARKS.md B6 for the current total.)
