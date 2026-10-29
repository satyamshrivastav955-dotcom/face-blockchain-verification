import { useEffect, useState } from "react";
import { api, ApiError, type CheckState, type Health, type VerifyReport } from "./api";
import { Stamp, reducedMotion } from "./ui";

const VERDICT: Record<string, { text: string; stamp: string; tone: "ok" | "err" | "warn" | "mute" }> = {
  verified: { text: "Unmodified, anchored, and the URL commitment matches.", stamp: "Verified", tone: "ok" },
  local_hash_mismatch: { text: "Failed local checks: modified, wrong image, or unverifiable.", stamp: "Failed", tone: "err" },
  not_anchored: { text: "The hash is not registered on the ledger.", stamp: "Not anchored", tone: "err" },
  anchor_mismatch: { text: "Anchored, but the record conflicts with the on-chain commitment.", stamp: "Conflict", tone: "err" },
  inconclusive: { text: "A required check could not be completed. Nothing is claimed either way.", stamp: "Inconclusive", tone: "warn" },
};

const CHECKS: Record<string, string> = {
  local_integrity: "Local integrity — hash recomputed from the payload",
  image_binding: "Image binding — record describes this file",
  evidence_bundle: "Evidence bundle — manifest and cross-links",
  chain_anchor: "Ledger anchor — hash is registered",
  url_commitment: "URL commitment — keccak256 of the URL equals the on-chain value",
};

const WORD: Record<CheckState, string> = { pass: "PASS", fail: "FAIL", error: "COULD NOT RUN", skipped: "NOT CHECKED" };
const TONE: Record<CheckState, "ok" | "err" | "warn" | "mute"> = { pass: "ok", fail: "err", error: "warn", skipped: "mute" };

/** Checks resolve one at a time (cosmetic stagger only; the values are the verifier's real results). */
export function VerifyResult({ report }: { report: VerifyReport }) {
  const entries = Object.entries(report.checks);
  const [shown, setShown] = useState(reducedMotion() ? entries.length + 1 : 0);
  useEffect(() => {
    if (reducedMotion()) return;
    setShown(0);
    const ids = entries.map((_, i) => window.setTimeout(() => setShown(i + 1), 260 * (i + 1)));
    const last = window.setTimeout(() => setShown(entries.length + 1), 260 * (entries.length + 1) + 120);
    return () => [...ids, last].forEach(window.clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report]);
  const v = VERDICT[report.verdict] ?? { text: report.verdict, stamp: report.verdict, tone: "mute" as const };

  return (
    <div className="examination" aria-live="polite">
      <ol className="exam-list">
        {entries.map(([name, c], i) => (
          <li key={name} className={i < shown ? "in" : ""}>
            <span className="exam-no">{String(i + 1).padStart(2, "0")}</span>
            <div>
              <b>{CHECKS[name] ?? name}</b>
              <p>{c.detail}</p>
            </div>
            <span className={`result-tag ${TONE[c.status]}`}>{i < shown ? WORD[c.status] : "…"}</span>
          </li>
        ))}
      </ol>

      <div className={`verdict ${shown > entries.length ? "in" : ""}`}>
        <div>
          <p className="folio">Verdict · exit code {report.exit_code}</p>
          <p className="verdict-text">{v.text}</p>
          {report.message && <p className="muted">{report.message}</p>}
          {report.simulated && <p className="notice warn"><b>Simulated.</b> Checked against a local JSON file, not a blockchain.</p>}
          {report.test_only && <p className="notice warn"><b>Test-only record</b> (stub engine / offline fixture).</p>}
          {report.chain && !report.simulated && report.chain.block_number !== undefined && (
            <dl className="facts">
              <dt>Network</dt><dd>{report.chain.network} (chain id {report.chain.chain_id})</dd>
              <dt>Contract</dt><dd className="mono wrap">{report.chain.contract_address}</dd>
              <dt>Block</dt><dd>{report.chain.block_number}</dd>
              {report.chain.tx_hash && (<><dt>Transaction</dt><dd className="mono wrap">{report.chain.tx_hash}</dd></>)}
              {report.chain.explorer_url && (<><dt>Explorer</dt><dd><a href={report.chain.explorer_url} target="_blank" rel="noreferrer noopener">open</a></dd></>)}
            </dl>
          )}
        </div>
        <div className="verdict-stamp">
          {shown > entries.length && <Stamp tone={v.tone} big tilt={-7}>{v.stamp}</Stamp>}
        </div>
      </div>
      <p className="muted">What this does not prove: that the underlying claim is true, that the URL was authentic, or who a person in an image is.</p>
      <details className="log-box"><summary>Verifier log</summary><pre className="log">{report.log.join("\n")}</pre></details>
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
    <div className="casefile">
      <header className="case-head">
        <p className="folio">Examination</p>
        <h1 className="h1">Examine a record</h1>
        <p className="lede">
          The record&apos;s hash is recomputed, optionally bound to the original image, then looked up on the ledger. A check that cannot run is never
          reported as a pass.
        </p>
      </header>
      <div className="exam-grid">
        <form className="plate" onSubmit={submit}>
          <h2><span className="tag-ex">Intake</span> Record and image</h2>
          <label className="field">
            <span>Verification record (JSON, up to {Math.round(health.limits.record_bytes / 1048576)} MiB)</span>
            <input type="file" accept="application/json,.json" onChange={(e) => setRecord(e.target.files?.[0] ?? null)} />
          </label>
          <label className="field">
            <span>Optional: the original image — checks the record describes exactly this file</span>
            <input type="file" accept="image/*" onChange={(e) => setImage(e.target.files?.[0] ?? null)} />
          </label>
          <label className="check">
            <input type="checkbox" checked={simulated} onChange={(e) => setSimulated(e.target.checked)} />
            <span>Check against the simulated local ledger instead of the real chain</span>
          </label>
          {!health.chain.contract_configured && !simulated && (
            <p className="notice warn">No registry address is configured on this server, so the ledger check will be inconclusive.</p>
          )}
          {error && <p className="notice err" role="alert">{error}</p>}
          <button type="submit" className="btn solid" disabled={!record || busy}>{busy ? "Examining…" : "Examine record"}</button>
          <p className="muted">Read-only on {health.chain.name}: no key and no gas needed.</p>
        </form>
        <section aria-live="polite" aria-label="Examination result">
          {report ? <VerifyResult report={report} /> : <p className="empty">The numbered findings and verdict will be filed here.</p>}
        </section>
      </div>
    </div>
  );
}
