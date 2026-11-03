# Privacy and legal posture

> **Not legal advice.** This is an engineering description of what the software does with personal data,
> plus the legal framing the maintainer worked from. The legal summary of India's DPDP Act below comes from
> secondary sources (compliance-vendor summaries, retrieved 2026-11-02), **not from the Gazette text**. Read
> the primary text, or ask counsel, before relying on any date or section number here.

## 1. The position in one paragraph

FaceProof is an **image-provenance** tool. Its default and recommended mode (`attest`, the browser verifier)
**never detects, embeds or compares a face** and never leaves the machine. An optional, consent-gated *trace*
mode analyses faces locally to re-check search leads; it produces a *similarity measurement*, never an
identification, and says so in the record. No mode maps a face to a name, builds a gallery, or searches a
database of people.

## 2. What data exists, where, and for how long

| Data | Created by | Where it lives | Leaves the machine? | Retention |
|---|---|---|---|---|
| Your image | you | where you keep it | **Never** by `attest` / verifier. Trace mode sends it (or a public URL) to the chosen search provider only after an explicit consent flag naming the provider | Yours. FaceProof copies it nowhere except evidence bundles in trace mode |
| Attestation record | `attest` | the file you save | Only the 32-byte record hash goes to OpenTimestamps calendars, and only with `--consent-timestamp-calendars` | Yours. The record contains **no face data and no filename** |
| Face embedding (trace mode) | local model | process memory only | **Never** saved, sent or put on-chain | Discarded when the process ends |
| Embedding commitment (trace records) | SHA-256 of a fixed-precision rendering of the embedding | inside the face-match record | Not sent; the record may be shared by you | Treat as personal data: whoever holds the same embedding can confirm it. It is a commitment, not anonymisation |
| Face crops, downloaded candidate images (trace mode) | pipeline | `evidence/<run>/` | No | Until you run `purge-evidence`; `--minimal-evidence` keeps none |
| Signing key | `keygen` | a file you choose | No | Yours; unencrypted at rest |
| Anything on a blockchain | `register --anchor chain` | public ledger | Yes, public and permanent | **Forever.** Only `sha256` of the record and `keccak256(url)`; never a face, vector, image or URL |
| Verifier page | your browser | memory | Only GETs for public Bitcoin block headers (visible in the page's network log) | Nothing is stored; there is no analytics, cookie or account |

A **public timestamp or ledger entry cannot be deleted**. That is the point of an anchor, and it is the main
tension with erasure rights (section 5).

## 3. Biometric data handling

* Face templates are computed only in trace mode, only on the machine that runs it, and are never persisted.
* The recorded fingerprint of an embedding is hashed with SHA-256 over a rounded text form. This hides the
  vector but **does not anonymise** it: it is linkable by anyone who can recompute the same embedding from the
  same face with the same model. Records produced in trace mode should be handled as personal data, and they
  carry `"embedding_on_chain": false`.
* Models used: OpenCV YuNet + SFace (permissive licences) by default; InsightFace weights are **non-commercial
  research only** and are opt-in. The licence is written into every record.
* **Measured error rates are not demographic-fair claims.** LFW is not demographically balanced and no
  per-group evaluation was run (see `BENCHMARKS.md`). NIST's own 2026 reporting notes persistent demographic
  differentials across the field. Do not use face-match output to make decisions about people.
* No liveness detection, no age/gender/emotion inference, no gallery of enrolled people: none is implemented.

## 4. No identification claims (a design rule, enforced in text)

* A face match is worded as "a face in the candidate image is similar to the query face under this model and
  threshold". An image-derivative match says it is *about the image, not faces or people*.
* The user interface says, on every page, that it never identifies a person. Records list their limitations.
* The verifier and `attest` modes cannot make such a claim because they process no face.
* Tracing is **one-to-many** against whatever a search provider returns, which is the part of the pipeline a
  reviewer will question. It is off by default, needs consent flags per provider, shows what would be sent
  before sending, and is documented in `docs/DECISIONS.md` D2.

## 5. India: DPDP Act 2023 and Rules 2025 (secondary-source summary)

What the sources agree on:

* The Act has **no separate "sensitive personal data" or biometric category**: biometric/face data is personal
  data like any other and the general obligations apply. Heightened duties come from being designated a
  Significant Data Fiduciary (s.10).
* The DPDP Rules were notified on 13 November 2025 and phase in over about 18 months: some provisions
  immediately, the consent-manager framework from about November 2026, and the **core obligations (notice,
  consent, security safeguards, breach notification, data-principal rights, erasure) from about May 2027**.
  Sources differ by a day on exact dates.
* Consent must be free, specific, informed, unconditional and unambiguous; notices must state purposes, data
  categories, retention and how to withdraw. Erasure is required when consent is withdrawn or the purpose is no
  longer served (s.8(7)), subject to other laws.

What this means for a deployer of FaceProof (not for a person using it on their own photos):

| Obligation (as understood) | How the software helps | What it does not do |
|---|---|---|
| Notice and consent before processing | Trace mode refuses to run without consent flags and prints exactly what is sent and to whom | It cannot obtain consent from the *people in the photograph*. That is the operator's duty |
| Purpose limitation, data minimisation | `attest` stores no face data and no filename; `--minimal-evidence` keeps no crops or downloads | Nothing stops an operator from using trace output for another purpose |
| Erasure | `purge-evidence` deletes local bundles; the app deletes job files after an hour; records are plain files you can delete | **Anchored hashes cannot be erased.** Mitigation: they are hashes, and an attestation hash reveals nothing about content. For trace records the anchored value commits to a record that may be personal data, so do not anchor trace records about people who have not consented |
| Security safeguards | Local-first design, SSRF-guarded downloads, signed records, threat model | No authentication in the local app; no encryption at rest; no audit log |
| Breach notification | n/a locally | An operator running a shared service needs their own process |
| Children's data | n/a | No age detection. Do not process images of children without verifiable parental consent |

**Recommended deployment posture:** use `attest` and the static verifier for provenance; use trace mode only
on images you own or have a lawful basis to process, only with the person's consent, and do not anchor trace
records that embed a face commitment unless that consent covers a permanent public record.

## 6. Other jurisdictions (flag only; not analysed)

If you operate outside India or process images of people in the EU/UK (GDPR: biometric data used to identify is
special-category data), the US (Illinois BIPA and similar), or elsewhere, different rules apply and several are
stricter. Nothing here covers them.

## 7. Deletion, in practice

```bash
python -m src.main purge-evidence --older-than-days 0.001 --yes   # local evidence bundles (a value of 0 is refused)
rm output/*.json                                                  # records are ordinary files
```

Then delete the signing key if you want to retire an identity. Anything already timestamped or anchored
remains, by design.

## 8. Third parties you may contact (all opt-in)

| Service | Receives | When |
|---|---|---|
| Search provider (SerpApi, TinEye) | the image or a public URL to it | trace mode, with `--consent-external-search` |
| Public image host | the image | only with `--consent-public-upload` |
| OpenTimestamps calendars | the 32-byte record hash and your IP | `--consent-timestamp-calendars` |
| Bitcoin block explorers | a block height (and your IP) | verification of a Bitcoin timestamp |
| EVM RPC node | the record hash and URL commitment | EVM anchoring and verification |
| Candidate websites | an HTTP request from your IP | trace mode downloads |

No third party gets a retention or deletion promise from FaceProof; check theirs.
