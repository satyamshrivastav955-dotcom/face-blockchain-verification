# Verification record format, algorithms and migration

## Layout

```jsonc
{
  "schema": "faceverify/v2",                 // envelope schema
  "payload": { ... },                        // the claim - this is what gets hashed
  "integrity": {
    "algorithm": "sha256-jcs-rfc8785-restricted-v1",
    "verification_hash": "0x<64 hex>",       // SHA-256 of canonical(payload)
    "canonical_length": 2637
  },
  "anchor": { ... } | null                   // written AFTER hashing; never part of the hash
}
```

`anchor` holds where the hash was registered (network, chain id, contract, registry version, tx hash,
block, submitter, URL commitment, `simulated`). It is deliberately outside the hashed payload: a
transaction id cannot exist before the hash does. `verify` therefore never trusts it - it recomputes
the hash and asks the chain.

### Payload (schema v2)

| Section | Contents |
|---|---|
| `schema`, `created_at` | schema id, UTC time to the second |
| `evidence_type` | `face_match` or `image_derivative` (see README > Match types) |
| `test_mode` | present only for stub-engine / offline-fixture records: `{stub_engine, offline_fixture_provider}` |
| `source_image` | filename, SHA-256, size, width, height, pHash |
| `face` | engine, model file names **and SHA-256 of the loaded weights**, face counts, `embedding_commitment_sha256`, `embedding_on_chain: false` |
| `search` | provider, endpoint, search time, raw-response SHA-256, candidate-table SHA-256, counts (`candidates_unmeasured` = skipped for technical reasons), `offline_stub` |
| `match` | evidence type, `decision_rule`, both check results (`face_check_passed`, `image_derivative_check_passed`), matched URL + `matched_url_commitment` (keccak256), image URL/SHA-256/pHash, scores and thresholds (strings), `claim`, `limitations` |

Scores are fixed-precision **strings** (`"0.9457"`); floats are not allowed in a hashed payload.

`embedding_commitment_sha256` is a SHA-256 over a fixed-precision text rendering of the face embedding.
It is a **commitment**, not anonymisation: it does not reveal the vector, but anyone who holds the same
embedding can confirm it. Treat the record as personal data. No raw embedding is saved in the record, the
evidence bundle or on-chain.

## Canonicalization: what is and is not claimed

`src/evidence/hashing.py` is a **restricted profile of RFC 8785 (JCS)**, not a full implementation.
For every input it accepts, its output is byte-identical to RFC 8785 (UTF-16 key ordering, recursive
sorting, JSON string escaping, no whitespace, UTF-8). It rejects what JCS would handle but this project
does not need:

* floats (ES6 number formatting is not implemented);
* integers outside +/-(2^53 - 1) (beyond which ES6 and Python disagree);
* lone surrogates (ill-formed Unicode);
* nesting deeper than 64.

Hence the declared name `sha256-jcs-rfc8785-restricted-v1`. Checked by `tests/test_canonical_vectors.py`:
the RFC 8785 section 3.2.2 string/literal example and the 3.2.3 UTF-16 sorting example, the restrictions
above, and an independent cross-check against JavaScript's `JSON.stringify` (runs when `node` is present).
The vectors were compared with the RFC text as published at rfc-editor.org (fetched 2026-10-29). The RFC's float vectors (Appendix B) are out of profile and are asserted to be *rejected*. Reference:
<https://www.rfc-editor.org/rfc/rfc8785>.

## Algorithm labels and historical records

| Label | Used by | Verified how |
|---|---|---|
| `sha256-jcs-rfc8785-restricted-v1` | records written by this build | current rules |
| `sha256-jcs-rfc8785` | records written before this build | **historical rules** (`legacy=True`: same bytes, integers not range-checked) |
| anything else | - | **fails** with "unsupported integrity algorithm" |

A record is always verified under the algorithm it *declares*. It is never silently re-interpreted under a
different one, and re-labelling a historical record does not make it verify (tested).

## Schema versions

* `faceverify/v1` (historical): readable and verifiable locally; has no `evidence_type`; its `decision_rule`
  may be `confirmed_face_match` or `confirmed_image_derivative`, and its `claim` sentence always spoke of a
  face match - **read a v1 `confirmed_image_derivative` record's claim as image similarity only.**
  Old field `face.embedding_sha256` was renamed `embedding_commitment_sha256`.
* `faceverify/v2`: current.

Loading rejects: files over 5 MiB, invalid UTF-8/JSON, NaN/Infinity, non-object structures, a missing or
malformed `verification_hash`, unsupported schema, wrong section types, excessive nesting.

## Evidence bundle (`evidence/<run>/`)

`manifest.json` lists every file with size and SHA-256. `python -m src.main verify --evidence-dir DIR`
checks listed files (missing / modified), unlisted extra files, unsafe names in the manifest, and the
cross-links to the sealed record: `candidates.canonical.json` against `search.candidates_sha256`,
`search_response.raw.json` against `search.raw_response_sha256`, `matched_image.original` against
`match.matched_image_sha256`, and that `candidates.json` contains the matched candidate with the same
status and image digest.

**What the manifest cannot prove:** whoever can edit the bundle can also regenerate `manifest.json`, and the
manifest itself is not anchored. Only the digests committed inside the sealed (and anchored) record bind the
bundle to the claim. Files not committed that way (face crops, comparison image) are as trustworthy as
their storage.
