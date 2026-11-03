import { useState } from "react";
import { api, ApiError, type AttestResult, type Health } from "./api";
import { DropField, Stamp } from "./ui";

function download(name: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2) + "\n"], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function AttestPanel({ health }: { health: Health }) {
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const [sign, setSign] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AttestResult | null>(null);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    setResult(null);
    const form = new FormData();
    form.set("image", file);
    form.set("note", note);
    form.set("sign", String(sign && health.signing_configured));
    try {
      setResult(await api.attest(form));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  const s = result?.summary;
  return (
    <div className="casefile">
      <header className="case-head">
        <p className="folio">Attestation</p>
        <h1 className="h1">Attest an image</h1>
        <p className="lede">
          Write a sealed, optionally signed description of one file: its exact fingerprint, a similarity hash, and what its metadata declares. <b>No face is
          detected, compared or stored, and nothing leaves this machine.</b>
        </p>
      </header>

      <div className="exam-grid">
        <form className="plate" onSubmit={submit}>
          <h2><span className="tag-ex">Intake</span> The file</h2>
          <DropField label="Image" hint="JPEG, PNG, WebP or GIF" accept="image/*" file={file} onFile={setFile} />
          <label className="field">
            <span>Optional note stored in the record (max 500 characters)</span>
            <textarea value={note} maxLength={500} rows={2} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Original from the 2026-03 site visit" />
          </label>
          <label className="check">
            <input type="checkbox" checked={sign && health.signing_configured} disabled={!health.signing_configured} onChange={(e) => setSign(e.target.checked)} />
            <span>
              Sign with this server&apos;s key {health.signing_configured ? "(Ed25519)" : "- none configured"}
              {!health.signing_configured && (
                <small className="sub">Create one with <code>python -m src.main keygen --out key.pem</code>, then set <code>SIGNING_KEY_FILE</code>. Unsigned records have no author.</small>
              )}
            </span>
          </label>
          {error && <p className="notice err" role="alert">{error}</p>}
          <button type="submit" className="btn solid" disabled={!file || busy}>{busy ? "Sealing…" : "Seal the record"}</button>
          <p className="muted">Read only on your file. To add time evidence, timestamp the record with the CLI (<code>attest --anchor ots</code>).</p>
        </form>

        <section aria-live="polite" aria-label="Attestation result">
          {result && s ? (
            <div className="plate attest-result">
              <div className="plate-stamp"><Stamp tone="ok" tilt={-6}>Sealed</Stamp></div>
              <h2><span className="tag-ex">Record</span> What was written</h2>
              <dl className="facts">
                <dt>SHA-256 of the file</dt><dd className="mono wrap">{s.sha256}</dd>
                <dt>Similarity hash</dt><dd className="mono">{s.phash} <small>(finds look-alike copies; not an identity measure)</small></dd>
                <dt>Size</dt><dd>{s.width}×{s.height} px, {s.bytes.toLocaleString()} bytes</dd>
                <dt>Content Credentials</dt><dd>{s.content_credentials} <small>(absence proves nothing)</small></dd>
                <dt>Synthetic-media declaration</dt>
                <dd>{s.synthetic_declaration === "declared_synthetic" ? "metadata declares generative AI" : "none declared"} <small>(read from metadata: not a detector, not proof)</small></dd>
                <dt>Record hash</dt><dd className="mono wrap">{s.verification_hash}</dd>
                <dt>Signature</dt><dd>{s.signed ? `Ed25519, key ${s.key_id}` : "unsigned: no author"}</dd>
                <dt>Anchor</dt><dd>none yet: no time evidence</dd>
              </dl>
              <div className="cta">
                <button className="btn solid" type="button" onClick={() => download(`faceproof-${s.sha256.slice(0, 12)}.json`, result.record)}>Download the record</button>
                <a className="btn" href="#/record">Examine it</a>
              </div>
              <p className="notice warn">
                Keep this record next to the image. Anyone can check them together at <a href="/verifier/" target="_blank" rel="noreferrer noopener">the standalone verifier</a>, in their
                own browser. A match proves the file is byte-for-byte the one described, not that it is genuine.
              </p>
            </div>
          ) : (
            <p className="empty">The sealed record will be filed here. Nothing is stored on the server: close this page and it is gone.</p>
          )}
        </section>
      </div>
    </div>
  );
}
