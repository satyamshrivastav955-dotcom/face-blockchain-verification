// FaceProof client-side verifier core. Pure functions, no DOM, no network (fetching is injected).
//
// Mirrors the Python verifier for the checks that need no secrets and no RPC:
//   local integrity (restricted RFC 8785 + SHA-256), Ed25519 signature, image binding, OpenTimestamps.
// NOT done here: EVM registry lookups (need an RPC), face analysis (by design: the verifier never
// touches a face), and perceptual hashing (exact SHA-256 only).
//
// Written in erasable TypeScript so `node --test` can run it directly.

export type CheckStatus = "pass" | "fail" | "error" | "skipped";
export interface Check {
  status: CheckStatus;
  detail: string;
}
export interface Report {
  verdict: "verified" | "failed" | "inconclusive" | "not_anchored";
  checks: Record<string, Check>;
  facts: Record<string, string>;
}
export type HeaderFetcher = (height: number) => Promise<Uint8Array>;

export const MAX_SAFE = Number.MAX_SAFE_INTEGER;
const HASH_RE = /^0x[0-9a-fA-F]{64}$/;
const HEX32_RE = /^[0-9a-fA-F]{64}$/;
const ALGORITHMS = ["sha256-jcs-rfc8785-restricted-v1", "sha256-jcs-rfc8785"];
const SCHEMAS = ["faceverify/v1", "faceverify/v2", "faceproof/attestation/v1"];
const DOMAIN = new TextEncoder().encode("faceproof-record-v1\u0000");

// ---------------------------------------------------------------- bytes helpers

export function hex(bytes: Uint8Array): string {
  let out = "";
  for (const b of bytes) out += b.toString(16).padStart(2, "0");
  return out;
}

export function fromHex(s: string): Uint8Array {
  const clean = s.startsWith("0x") ? s.slice(2) : s;
  if (clean.length % 2 !== 0 || /[^0-9a-fA-F]/.test(clean)) throw new Error("invalid hex");
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export function fromBase64(s: string): Uint8Array {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export async function sha256(data: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", data as BufferSource));
}

export async function sha256Hex(data: Uint8Array): Promise<string> {
  return hex(await sha256(data));
}

// ---------------------------------------------------------------- canonicalisation

export class CanonicalError extends Error {}

function hasLoneSurrogate(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const n = s.charCodeAt(i + 1);
      if (!(n >= 0xdc00 && n <= 0xdfff)) return true;
      i++;
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      return true;
    }
  }
  return false;
}

// Restricted RFC 8785: integers within +/-(2^53-1) only (legacy records accept larger ints, which a
// JS number cannot represent exactly, so those are reported as "cannot check here"), no floats,
// no lone surrogates, depth <= 64. Object keys sort by UTF-16 code unit, which is JS's default
// string comparison.
export function canonicalize(value: unknown, depth = 0): string {
  if (depth > 64) throw new CanonicalError("nesting deeper than 64");
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "string") {
    if (hasLoneSurrogate(value)) throw new CanonicalError("lone surrogate in string");
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isInteger(value)) throw new CanonicalError("floats are not canonicalizable");
    if (Math.abs(value) > MAX_SAFE) throw new CanonicalError("integer outside +/-(2^53-1)");
    return String(value);
  }
  if (Array.isArray(value)) return "[" + value.map((v) => canonicalize(v, depth + 1)).join(",") + "]";
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj).sort();
    return (
      "{" +
      keys
        .map((k) => {
          if (hasLoneSurrogate(k)) throw new CanonicalError("lone surrogate in key");
          return JSON.stringify(k) + ":" + canonicalize(obj[k], depth + 1);
        })
        .join(",") +
      "}"
    );
  }
  throw new CanonicalError("unsupported type " + typeof value);
}

export async function payloadHash(payload: unknown): Promise<string> {
  return "0x" + (await sha256Hex(new TextEncoder().encode(canonicalize(payload))));
}

// ---------------------------------------------------------------- signature

export async function verifySignature(
  record: any,
  recomputed: string,
  trusted: string[],
): Promise<{ state: "unsigned" | "valid" | "invalid" | "unsupported"; pinned: boolean | null; keyId: string; detail: string }> {
  const sig = record.signature;
  const pins = trusted.map((k) => k.toLowerCase());
  if (sig === undefined || sig === null) {
    return pins.length
      ? { state: "invalid", pinned: false, keyId: "", detail: "a trusted key was required but the record is unsigned" }
      : { state: "unsigned", pinned: null, keyId: "", detail: "the record carries no signature" };
  }
  if (typeof sig !== "object" || sig.algorithm !== "ed25519" || !HEX32_RE.test(String(sig.public_key)) || typeof sig.signature !== "string" || typeof sig.signed_hash !== "string") {
    return { state: "invalid", pinned: null, keyId: "", detail: "signature block is malformed or uses an unsupported algorithm" };
  }
  const pub = String(sig.public_key).toLowerCase();
  const keyId = hex(await sha256(fromHex(pub))).slice(0, 16);
  if (String(sig.signed_hash).toLowerCase() !== recomputed.toLowerCase()) {
    return { state: "invalid", pinned: null, keyId, detail: "signature covers a different hash than the payload now has" };
  }
  let ok = false;
  try {
    const key = await crypto.subtle.importKey("raw", fromHex(pub) as BufferSource, { name: "Ed25519" }, false, ["verify"]);
    const msg = new Uint8Array(DOMAIN.length + 32);
    msg.set(DOMAIN, 0);
    msg.set(fromHex(recomputed), DOMAIN.length);
    ok = await crypto.subtle.verify({ name: "Ed25519" }, key, fromHex(sig.signature) as BufferSource, msg as BufferSource);
  } catch {
    return { state: "unsupported", pinned: null, keyId, detail: "this browser cannot verify Ed25519 signatures (WebCrypto)" };
  }
  if (!ok) return { state: "invalid", pinned: null, keyId, detail: "signature does not verify" };
  const pinned = pins.length ? pins.includes(pub) : null;
  const detail =
    pinned === true
      ? "valid signature by a pinned key"
      : pinned === false
        ? "valid signature, but by a key that is not in the trusted set"
        : "valid signature; signer key NOT pinned (proves consistency, not identity)";
  return { state: "valid", pinned, keyId, detail };
}

// ---------------------------------------------------------------- OpenTimestamps

class Reader {
  pos = 0;
  b: Uint8Array;
  constructor(b: Uint8Array) {
    this.b = b;
  }
  byte(): number {
    if (this.pos >= this.b.length) throw new Error("truncated OTS proof");
    return this.b[this.pos++];
  }
  take(n: number): Uint8Array {
    if (n < 0 || this.pos + n > this.b.length) throw new Error("truncated OTS proof");
    const out = this.b.slice(this.pos, this.pos + n);
    this.pos += n;
    return out;
  }
  varuint(): number {
    let value = 0;
    let shift = 1;
    for (let i = 0; i < 6; i++) {
      const c = this.byte();
      value += (c & 0x7f) * shift;
      if (!(c & 0x80)) return value;
      shift *= 128;
    }
    throw new Error("varuint too long");
  }
  varbytes(max = 8192): Uint8Array {
    const n = this.varuint();
    if (n > max) throw new Error("OTS field too large");
    return this.take(n);
  }
}

const OTS_MAGIC = Uint8Array.from([
  0x00, 0x4f, 0x70, 0x65, 0x6e, 0x54, 0x69, 0x6d, 0x65, 0x73, 0x74, 0x61, 0x6d, 0x70, 0x73, 0x00, 0x00, 0x50, 0x72, 0x6f, 0x6f, 0x66, 0x00, 0xbf, 0x89, 0xe2, 0xe8, 0x84, 0xe8, 0x92, 0x94,
]);
const BITCOIN_TAG = "0588960d73d71901";
const PENDING_TAG = "83dfe30d2ef90c8e";

export interface OtsLeaf {
  kind: "bitcoin" | "pending" | "other";
  msg: Uint8Array;
  height?: number;
  uri?: string;
}

async function applyOp(tag: number, msg: Uint8Array, arg: Uint8Array | null): Promise<Uint8Array> {
  switch (tag) {
    case 0x08:
      return sha256(msg);
    case 0xf0: {
      const out = new Uint8Array(msg.length + arg!.length);
      out.set(msg, 0);
      out.set(arg!, msg.length);
      return out;
    }
    case 0xf1: {
      const out = new Uint8Array(msg.length + arg!.length);
      out.set(arg!, 0);
      out.set(msg, arg!.length);
      return out;
    }
    case 0xf2:
      return Uint8Array.from(msg).reverse();
    case 0xf3:
      return new TextEncoder().encode(hex(msg));
    default:
      throw new Error("OTS operation 0x" + tag.toString(16) + " is not supported in the browser");
  }
}

async function walk(r: Reader, msg: Uint8Array, leaves: OtsLeaf[], depth: number): Promise<void> {
  if (depth > 256) throw new Error("OTS proof nests too deeply");
  let tag = r.byte();
  while (true) {
    const more = tag === 0xff;
    const t = more ? r.byte() : tag;
    if (t === 0x00) {
      const att = hex(r.take(8));
      const payload = new Reader(r.varbytes());
      if (att === BITCOIN_TAG) leaves.push({ kind: "bitcoin", msg, height: payload.varuint() });
      else if (att === PENDING_TAG) leaves.push({ kind: "pending", msg, uri: new TextDecoder().decode(payload.varbytes()) });
      else leaves.push({ kind: "other", msg });
    } else {
      const binary = t === 0xf0 || t === 0xf1;
      const arg = binary ? r.varbytes() : null;
      await walk(r, await applyOp(t, msg, arg), leaves, depth + 1);
    }
    if (!more) return;
    tag = r.byte();
  }
}

export async function parseOts(raw: Uint8Array): Promise<{ digest: Uint8Array; leaves: OtsLeaf[] }> {
  if (raw.length > 64 * 1024) throw new Error("OTS proof is larger than the allowed size");
  const r = new Reader(raw);
  const magic = r.take(OTS_MAGIC.length);
  if (hex(magic) !== hex(OTS_MAGIC)) throw new Error("not an OpenTimestamps proof");
  if (r.varuint() !== 1) throw new Error("unsupported OTS version");
  if (r.byte() !== 0x08) throw new Error("only SHA-256 OTS file digests are supported");
  const digest = r.take(32);
  const leaves: OtsLeaf[] = [];
  await walk(r, digest, leaves, 0);
  return { digest, leaves };
}

export async function checkOts(anchor: any, recomputed: string, fetchHeader: HeaderFetcher): Promise<Check & { height?: number; time?: number }> {
  let parsed;
  try {
    parsed = await parseOts(fromBase64(String(anchor.ots ?? "")));
  } catch (e) {
    return { status: "fail", detail: "unreadable OTS proof: " + (e as Error).message };
  }
  if (hex(parsed.digest) !== recomputed.replace(/^0x/, "").toLowerCase()) {
    return { status: "fail", detail: "the OTS proof stamps a different digest than this record's hash" };
  }
  const bitcoin = parsed.leaves.filter((l) => l.kind === "bitcoin").sort((a, b) => a.height! - b.height!);
  if (!bitcoin.length) {
    return parsed.leaves.some((l) => l.kind === "pending")
      ? { status: "fail", detail: "PENDING: stamped but not yet confirmed in a Bitcoin block" }
      : { status: "fail", detail: "the OTS proof contains no usable attestation" };
  }
  const errors: string[] = [];
  for (const leaf of bitcoin) {
    let header: Uint8Array;
    try {
      header = await fetchHeader(leaf.height!);
    } catch (e) {
      errors.push((e as Error).message);
      continue;
    }
    if (header.length !== 80) return { status: "fail", detail: "block header has the wrong length" };
    if (hex(header.slice(36, 68)) !== hex(leaf.msg)) {
      return { status: "fail", detail: "Bitcoin attestation at height " + leaf.height + " does not match the block's Merkle root" };
    }
    const time = new DataView(header.buffer, header.byteOffset + 68, 4).getUint32(0, true);
    return { status: "pass", detail: "hash existed by Bitcoin block " + leaf.height, height: leaf.height, time };
  }
  return { status: "error", detail: errors.join("; ").slice(0, 300) || "could not fetch a Bitcoin block header" };
}

// ---------------------------------------------------------------- whole record

export interface VerifyOptions {
  image?: Uint8Array | null;
  trustedKeys?: string[];
  requireImage?: boolean;
  fetchHeader?: HeaderFetcher;
}

function skipped(detail: string): Check {
  return { status: "skipped", detail };
}

export async function verifyRecord(record: any, opts: VerifyOptions = {}): Promise<Report> {
  const checks: Record<string, Check> = {
    local_integrity: skipped(""),
    signature: skipped("record is unsigned"),
    image_binding: skipped("no image provided"),
    anchor: skipped(""),
  };
  const facts: Record<string, string> = {};
  const done = (verdict: Report["verdict"]): Report => ({ verdict, checks, facts });

  if (!record || typeof record !== "object" || typeof record.payload !== "object" || record.payload === null || typeof record.integrity !== "object" || record.integrity === null) {
    checks.local_integrity = { status: "fail", detail: "not a FaceProof record" };
    return done("failed");
  }
  const schema = record.schema ?? record.payload.schema;
  if (!SCHEMAS.includes(schema)) {
    checks.local_integrity = { status: "fail", detail: "unsupported schema " + String(schema).slice(0, 40) };
    return done("failed");
  }
  facts.schema = String(schema);
  const stored = String(record.integrity.verification_hash ?? "");
  if (!HASH_RE.test(stored)) {
    checks.local_integrity = { status: "fail", detail: "verification_hash is not 0x + 64 hex digits" };
    return done("failed");
  }
  if (!ALGORITHMS.includes(record.integrity.algorithm)) {
    checks.local_integrity = { status: "fail", detail: "unsupported integrity algorithm" };
    return done("failed");
  }
  let recomputed: string;
  try {
    recomputed = await payloadHash(record.payload);
  } catch (e) {
    checks.local_integrity = { status: "error", detail: "cannot canonicalize in the browser: " + (e as Error).message };
    return done("inconclusive");
  }
  facts.recomputed_hash = recomputed;
  if (recomputed.toLowerCase() !== stored.toLowerCase()) {
    checks.local_integrity = { status: "fail", detail: "the payload does not match its stored hash: it was modified" };
    return done("failed");
  }
  checks.local_integrity = { status: "pass", detail: "payload matches its stored hash" };

  // image binding
  const declared = String(record.payload.source_image?.sha256 ?? "").toLowerCase();
  if (opts.image) {
    const actual = await sha256Hex(opts.image);
    facts.image_sha256 = actual;
    if (actual !== declared) {
      checks.image_binding = { status: "fail", detail: "this file's SHA-256 differs from the record's: it is not the attested file" };
      return done("failed");
    }
    checks.image_binding = { status: "pass", detail: "the file is byte-for-byte the attested image" };
  } else if (opts.requireImage) {
    checks.image_binding = { status: "error", detail: "an image is required but none was chosen" };
    return done("inconclusive");
  }

  // signature
  const sig = await verifySignature(record, recomputed, opts.trustedKeys ?? []);
  if (sig.state === "valid" && sig.pinned === false) {
    checks.signature = { status: "fail", detail: sig.detail };
    return done("failed");
  }
  if (sig.state === "valid") {
    checks.signature = { status: "pass", detail: sig.detail };
    facts.key_id = sig.keyId;
  } else if (sig.state === "invalid") {
    checks.signature = { status: "fail", detail: sig.detail };
    return done("failed");
  } else if (sig.state === "unsupported") {
    checks.signature = { status: "error", detail: sig.detail };
    return done("inconclusive");
  }

  // anchor
  const anchor = record.anchor;
  if (anchor && anchor.mode === "opentimestamps") {
    if (!opts.fetchHeader) {
      checks.anchor = { status: "error", detail: "no block-header source configured" };
      return done("inconclusive");
    }
    const res = await checkOts(anchor, recomputed, opts.fetchHeader);
    checks.anchor = { status: res.status, detail: res.detail };
    if (res.height !== undefined) {
      facts.bitcoin_block = String(res.height);
      facts.block_time = new Date((res.time ?? 0) * 1000).toISOString();
    }
    if (res.status === "pass") return done("verified");
    if (res.status === "error") return done("inconclusive");
    return done(res.detail.startsWith("PENDING") || res.detail.startsWith("the OTS proof contains no") ? "not_anchored" : "failed");
  }
  if (anchor && (anchor.tx_hash || anchor.mode === "merkle_batch")) {
    checks.anchor = { status: "error", detail: "an EVM-registry anchor needs an RPC lookup, which this page does not do. Use the CLI: python -m src.main verify" };
    return done("inconclusive");
  }
  checks.anchor = { status: "fail", detail: "the record carries no anchor, so it has no time evidence" };
  return done("not_anchored");
}

// Block-header fetcher for browsers: cross-checks every reachable explorer; they must agree.
export function explorerFetcher(bases: string[], doFetch: typeof fetch = fetch): HeaderFetcher {
  return async (height: number) => {
    const got: string[] = [];
    const problems: string[] = [];
    for (const base of bases) {
      try {
        const h = await doFetch(`${base}/block-height/${height}`);
        if (!h.ok) throw new Error("HTTP " + h.status);
        const blockHash = (await h.text()).trim();
        if (!/^[0-9a-f]{64}$/.test(blockHash)) throw new Error("unexpected block hash");
        const hd = await doFetch(`${base}/block/${blockHash}/header`);
        if (!hd.ok) throw new Error("HTTP " + hd.status);
        got.push((await hd.text()).trim());
      } catch (e) {
        problems.push(`${base}: ${(e as Error).message}`);
      }
    }
    if (!got.length) throw new Error("no block explorer answered (" + problems.join("; ") + ")");
    if (new Set(got).size > 1) throw new Error("block explorers disagree about the header at height " + height);
    return fromHex(got[0]);
  };
}
