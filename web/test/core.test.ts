// Cross-implementation tests: the browser verifier must agree with the Python reference.
// Run: node --test web/test/   (Node >= 24 strips the types natively)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { canonicalize, fromBase64, fromHex, verifyRecord, explorerFetcher } from "../src/verifier/core.ts";

const V = JSON.parse(readFileSync(new URL("./vectors.json", import.meta.url), "utf8"));
const image = fromBase64(V.image_b64);
const header = fromHex(V.header_hex);
const fetchHeader = async (h: number) => {
  assert.equal(h, V.header_height);
  return header;
};
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

test("canonicalization matches the Python reference byte for byte", () => {
  for (const c of V.canonical) assert.equal(canonicalize(c.value), c.canonical);
});

test("floats and unsafe integers are refused, not mis-hashed", () => {
  assert.throws(() => canonicalize({ x: 1.5 }));
  assert.throws(() => canonicalize({ x: 2 ** 60 }));
  assert.throws(() => canonicalize({ x: "\ud800" }));
});

test("a signed, unanchored record: consistent and signed, but fails closed on time evidence", async () => {
  const r = await verifyRecord(V.records.signed_unanchored, { image });
  assert.equal(r.verdict, "not_anchored");
  assert.equal(r.checks.local_integrity.status, "pass");
  assert.equal(r.checks.signature.status, "pass");
  assert.equal(r.checks.image_binding.status, "pass");
});

test("a Bitcoin-attested record verifies, with the block time from the header", async () => {
  const r = await verifyRecord(V.records.signed_attested, { image, trustedKeys: [V.public_key], fetchHeader });
  assert.equal(r.verdict, "verified");
  assert.equal(r.facts.bitcoin_block, "800000");
  assert.equal(r.facts.block_time, "2023-11-14T22:13:20.000Z");
});

test("a pending timestamp is never a pass", async () => {
  const r = await verifyRecord(V.records.signed_pending, { image, fetchHeader });
  assert.equal(r.verdict, "not_anchored");
});

test("a wrong header fails; an unreachable explorer is inconclusive", async () => {
  const bad = Uint8Array.from(header);
  bad[40] ^= 0xff; // corrupt the Merkle root
  assert.equal((await verifyRecord(V.records.signed_attested, { image, fetchHeader: async () => bad })).verdict, "failed");
  const down = async () => {
    throw new Error("no block explorer answered");
  };
  assert.equal((await verifyRecord(V.records.signed_attested, { image, fetchHeader: down })).verdict, "inconclusive");
});

test("any payload edit is caught offline", async () => {
  const r = clone(V.records.signed_attested);
  r.payload.note = "edited";
  const out = await verifyRecord(r, { image, fetchHeader });
  assert.equal(out.verdict, "failed");
  assert.equal(out.checks.local_integrity.status, "fail");
});

test("a re-sealed edit keeps the old signature and is caught by it", async () => {
  const { payloadHash } = await import("../src/verifier/core.ts");
  const r = clone(V.records.signed_attested);
  r.payload.source_image.sha256 = "0".repeat(64);
  r.integrity.verification_hash = await payloadHash(r.payload);
  const out = await verifyRecord(r, { fetchHeader });
  assert.equal(out.verdict, "failed");
  assert.equal(out.checks.signature.status, "fail");
});

test("a different image is rejected", async () => {
  const other = Uint8Array.from(image);
  other[other.length - 20] ^= 1;
  const out = await verifyRecord(V.records.signed_attested, { image: other, fetchHeader });
  assert.equal(out.verdict, "failed");
  assert.equal(out.checks.image_binding.status, "fail");
});

test("pinning a different key fails; requiring an image without one is inconclusive", async () => {
  const pin = await verifyRecord(V.records.signed_attested, { image, trustedKeys: ["11".repeat(32)], fetchHeader });
  assert.equal(pin.verdict, "failed");
  const req = await verifyRecord(V.records.signed_attested, { requireImage: true, fetchHeader });
  assert.equal(req.verdict, "inconclusive");
});

test("an EVM-anchored record is reported as not checkable here, never as verified", async () => {
  const r = clone(V.records.signed_unanchored);
  r.anchor = { tx_hash: "0x" + "ab".repeat(32), mode: "single" };
  const out = await verifyRecord(r, {});
  assert.equal(out.verdict, "inconclusive");
});

test("garbage input fails without throwing", async () => {
  for (const x of [null, 1, "x", {}, { payload: {}, integrity: {} }]) {
    const out = await verifyRecord(x as never, {});
    assert.equal(out.verdict, "failed");
  }
});

test("explorer fetcher requires agreement between explorers", async () => {
  const mk = (hdr: string) => async (url: string | URL | Request) => {
    const u = String(url);
    return u.includes("/block-height/")
      ? new Response("a".repeat(64))
      : new Response(hdr);
  };
  const one = explorerFetcher(["https://a", "https://b"], mk(V.header_hex) as never);
  assert.equal((await one(800000)).length, 80);
  let n = 0;
  const split = (async (url: string) => {
    if (String(url).includes("/block-height/")) return new Response("a".repeat(64));
    return new Response(n++ === 0 ? V.header_hex : "00".repeat(80));
  }) as never;
  await assert.rejects(explorerFetcher(["https://a", "https://b"], split)(800000), /disagree/);
});
