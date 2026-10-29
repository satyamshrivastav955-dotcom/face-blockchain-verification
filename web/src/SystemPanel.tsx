import type { Health } from "./api";

function Row({ k, v, state }: { k: string; v: string; state?: "ok" | "warn" }) {
  return (
    <tr>
      <th scope="row">{k}</th>
      <td>{state && <span className={`dot ${state}`} aria-hidden="true" />}{v}</td>
    </tr>
  );
}

export function SystemPanel({ health }: { health: Health }) {
  return (
    <div className="narrow">
      <p className="eyebrow">System</p>
      <h1 className="h1">Readiness, as the server sees it</h1>
      <p className="lede">These are live values from <code>/api/health</code>. No secret is ever returned, only whether it is set.</p>
      <div className="card">
        <table className="kv">
          <tbody>
            <Row k="Version" v={health.version} />
            <Row k="Mode" v={health.demo_mode ? "Demo (stub engine + fixture enabled)" : "Standard"} state={health.demo_mode ? "warn" : "ok"} />
            <Row k="Face models" v={health.models_present ? "present" : "missing: run scripts/fetch_models.py"} state={health.models_present ? "ok" : "warn"} />
            <Row k="Search provider" v={health.search_provider} />
            <Row k="Search key configured" v={health.search_configured ? "yes" : "no"} state={health.search_configured ? "ok" : "warn"} />
            <Row k="Chain" v={`${health.chain.name} (id ${health.chain.chain_id})`} />
            <Row k="Registry address configured" v={health.chain.contract_configured ? "yes" : "no (v2 not deployed or not set)"} state={health.chain.contract_configured ? "ok" : "warn"} />
            <Row k="Signer configured" v={health.chain.signer_configured ? "yes" : "no"} />
            <Row k="Real-chain writes from the UI" v={health.chain_writes_enabled ? "enabled (spends gas)" : "disabled: simulated chain only"} state={health.chain_writes_enabled ? "warn" : "ok"} />
            <Row k="Face cosine threshold" v={String(health.thresholds.face_cosine)} />
            <Row k="pHash max distance" v={`${health.thresholds.phash_max_distance} / 64`} />
            <Row k="Upload limit" v={`${Math.round(health.limits.upload_bytes / 1048576)} MiB`} />
          </tbody>
        </table>
      </div>
      <p className="muted">Thresholds depend on the model and data and are not calibrated for any population.</p>
    </div>
  );
}
