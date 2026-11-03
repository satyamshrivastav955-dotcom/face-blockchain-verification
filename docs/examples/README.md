# Examples

`live-ots-attestation.json` is a real attestation of `tests/data/query.png` (a synthetic image), signed with a
throwaway key, and timestamped on 2026-11-03 through the public OpenTimestamps calendars. It contains only hashes.

* Right after submission it is **pending**: `verify` exits 3 and says so.
* After the calendars' Bitcoin transaction confirms (hours), finish it with:

```bash
python -m src.main ots-upgrade --record docs/examples/live-ots-attestation.json
python -m src.main verify --record docs/examples/live-ots-attestation.json --image tests/data/query.png
```

The signing key is not in the repository; its public key is in the record (`signature.public_key`).
