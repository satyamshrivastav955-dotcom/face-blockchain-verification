import { useState } from "react";
import { api, ApiError, type CheckState, type Health, type VerifyReport } from "./api";

const VERDICT_TEXT: Record<string, string> = {
  verified: "VERIFIED: unmodified, anchored, URL commitment matches",
  local_hash_mismatch: "FAILED LOCAL CHECKS: modified, wrong image, or unverifiable",
  not_anchored: "NOT ANCHORED on the chain",
  anchor_mismatch: "CONFLICTS with the on-chain anchor",
  inconclusive: "INCONCLUSIVE: a required check could not be completed",
};

const CHECK_LABEL: Record<string, string> = {
  local_integrity: "Local integrity (hash recomputed from the payload)",
  image_binding: "Image binding (record describes this image file)",
  evidence_bundle: "Evidence bundle",
  chain_anchor: "Chain anchor (hash is registered)",
  url_commitment: "URL commitment (keccak256 of matched URL equals on-chain value)",
};

const STATE_WORD: Record<CheckState, string> = {
  pass: "PASS",
  fail: "FAIL",
  error: "COULD NOT RUN",
  skipped: "NOT CHECKED",
};

export function VerifyResult({ report }: { report: VerifyReport }) {
  return (
    <div className="result" aria-live="polite">
      <p className={`banner ${report.verdict === "verified" ? "ok" : report.verdict === "inconclusive" ? "warn" : "error"}`} role="status">
        <strong>{VERDICT_TEXT[report.verdict] ?? report.verdict}</strong> (exit code {report.exit_code})
      </p>
      {report.message && <p className="muted">{report.message}</p>}
      {report.simulated && (
        <p className="banner warn">
          <strong>SIMULATED:</strong> checked against a local JSON file, not a blockchain.
        </p>
      )}
      {report.test_only && (
        <p className="banner warn">
          <strong>TEST-ONLY record</strong> (stub engine / offline fixture).
        </p>
      )}
      <table>
        <caption>Individual checks</caption>
        <thead>
          <tr>
            <th scope="col">Check</th>
            <th scope="col">Result</th>
            <th scope="col">Detail</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(report.checks).map(([name, c]) => (
            <tr key={name}>
              <td>{CHECK_LABEL[name] ?? name}</td>
              <td>
                <span className={`pill ${c.status}`}>{STATE_WORD[c.status]}</span>
              </td>
              <td>{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {report.chain && !report.simulated && report.chain.block_number !== undefined && (
        <dl className="facts">
          <dt>Network</dt>
          <dd>
            {report.chain.network} (chain id {report.chain.chain_id})
          </dd>
          <dt>Contract</dt>
          <dd className="mono wrap">{report.chain.contract_address}</dd>
          <dt>Block</dt>
          <dd>{report.chain.block_number}</dd>
          {report.chain.tx_hash && (
            <>
              <dt>Transaction</dt>
              <dd className="mono wrap">{report.chain.tx_hash}</dd>
            </>
          )}
          {report.chain.explorer_url && (
            <>
              <dt>Explorer</dt>
              <dd>
                <a href={report.chain.explorer_url} target="_blank" rel="noreferrer noopener">
                  open
                </a>
              </dd>
            </>
          )}
        </dl>
      )}
      <p className="muted">
        What this does not prove: that the underlying claim is true, that the URL was authentic, or who the person in an image
        is.
      </p>
      <details>
        <summary>Verifier log</summary>
        <pre className="log">{report.log.join("\n")}</pre>
      </details>
    </div>
  );
}

export function VerifyPanel({ health }: { health: Health }) {
  const [record, setRecord] = useState<File | null>(null);
  const [image, setImage] = useState<File | null>(null);
  const [simulated, setSimulated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<VerifyReport | null>(null);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    if (!record) return;
    setBusy(true);
    setError("");
    setReport(null);
    const form = new FormData();
    form.set("record", record);
    if (image) form.set("image", image);
    form.set("simulated", String(simulated));
    try {
      setReport(await api.verify(form));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid">
      <form className="card" onSubmit={submit}>
        <h2>Check an existing record</h2>
        <p className="muted">
          Recomputes the record&apos;s hash, optionally binds it to the original image, then looks the hash up on {health.chain.name}{" "}
          (read-only; no key or gas needed). A failed lookup is reported as inconclusive, never as success.
        </p>
        <label className="field">
          <span>Verification record (JSON, up to {Math.round(health.limits.record_bytes / 1048576)} MiB)</span>
          <input type="file" accept="application/json,.json" onChange={(e) => setRecord(e.target.files?.[0] ?? null)} />
        </label>
        <label className="field">
          <span>Optional: the original image (checks the record describes exactly this file)</span>
          <input type="file" accept="image/*" onChange={(e) => setImage(e.target.files?.[0] ?? null)} />
        </label>
        <label className="check">
          <input type="checkbox" checked={simulated} onChange={(e) => setSimulated(e.target.checked)} />
          <span>Check against the simulated local chain instead of the real one</span>
        </label>
        {!health.chain.contract_configured && !simulated && (
          <p className="banner warn">No CONTRACT_ADDRESS is configured on this server, so the chain check will be inconclusive.</p>
        )}
        {error && (
          <p className="banner error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={!record || busy}>
          {busy ? "Checking..." : "Verify record"}
        </button>
      </form>
      <section aria-live="polite" aria-label="Verification result">
        {report ? (
          <div className="card">
            <VerifyResult report={report} />
          </div>
        ) : (
          <p className="muted empty card">The verification result appears here.</p>
        )}
      </section>
    </div>
  );
}
