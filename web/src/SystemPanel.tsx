import type { Health } from "./api";
import { Leader, Stamp } from "./ui";

export function SystemPanel({ health }: { health: Health }) {
  const ready = health.models_present || health.demo_mode;
  return (
    <div className="casefile">
      <header className="case-head">
        <p className="folio">Bureau status</p>
        <h1 className="h1">Readiness, as the server sees it</h1>
        <p className="lede">Live values from <code>/api/health</code>. No secret is ever returned, only whether it is set.</p>
      </header>
      <section className="plate wide">
        <div className="plate-stamp"><Stamp tone={ready ? "ok" : "warn"} tilt={-5}>{ready ? "Operational" : "Models missing"}</Stamp></div>
        <Leader k="Version" v={health.version} />
        <Leader k="Mode" v={health.demo_mode ? "Demonstration (stub engine + fixture enabled)" : "Standard"} />
        <Leader k="Face models" v={health.models_present ? "on file" : "missing: run scripts/fetch_models.py"} />
        <Leader k="Search provider" v={health.search_provider} />
        <Leader k="Search key set" v={health.search_configured ? "yes" : "no"} />
        <Leader k="Chain" v={`${health.chain.name} · id ${health.chain.chain_id}`} />
        <Leader k="Registry address set" v={health.chain.contract_configured ? "yes" : "no (v2 not deployed or not set)"} />
        <Leader k="Signer set" v={health.chain.signer_configured ? "yes" : "no"} />
        <Leader k="Real-chain writes from the UI" v={health.chain_writes_enabled ? "enabled (spends gas)" : "disabled — simulated ledger only"} />
        <Leader k="Face cosine threshold" v={String(health.thresholds.face_cosine)} />
        <Leader k="pHash limit" v={`${health.thresholds.phash_max_distance} / 64`} />
        <Leader k="Upload limit" v={`${Math.round(health.limits.upload_bytes / 1048576)} MiB`} />
      </section>
      <p className="muted">Thresholds depend on the model and data and are not calibrated for any population.</p>
    </div>
  );
}
