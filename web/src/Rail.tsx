import type { Health, JobStatus } from "./api";

const STATE_TEXT: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Registered",
  no_match: "No match",
  failed: "Failed",
  cancelling: "Cancelling",
  cancelled: "Cancelled",
};

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="rail-row">
      <dt>{k}</dt>
      <dd>{v}</dd>
    </div>
  );
}

/** Right-hand summary. Every value is derived from the job or /api/health; "–" means "not available yet". */
export function Rail({ job, health }: { job: JobStatus | null; health: Health }) {
  const measured = job?.candidates.filter((c) => !c.status.startsWith("skipped")) ?? [];
  const best = measured.length ? Math.max(...measured.map((c) => parseFloat(c.face_similarity))) : null;
  const rec = job?.record;
  const anchor = rec?.anchor;
  const simulated = job ? job.simulated_chain : true;
  return (
    <aside className="rail" aria-label="Summary">
      <section className="card">
        <header className="card-head">
          <h2>Verification result</h2>
          {health.demo_mode && <span className="chip">DEMO</span>}
        </header>
        {!job && <p className="hint">Upload an image to start. Results will appear here.</p>}
        <dl>
          <Row k="Status" v={job ? STATE_TEXT[job.status] ?? job.status : "–"} />
          <Row k="Candidates returned" v={job ? job.candidates.length : "–"} />
          <Row k="Measured locally" v={job ? measured.length : "–"} />
          <Row k="Highest face cosine" v={best !== null ? best.toFixed(4) : "–"} />
          <Row
            k="Evidence type"
            v={rec ? (rec.payload.match.decision_rule === "confirmed_face_match" ? "Face match" : "Image derivative") : "–"}
          />
          <Row k="Record" v={rec ? "sealed" : "–"} />
        </dl>
      </section>

      <section className="card">
        <header className="card-head">
          <h2>Chain status</h2>
          <span className={`chip ${simulated ? "warn" : "ok"}`}>{simulated ? "SIMULATED" : "LIVE"}</span>
        </header>
        <dl>
          <Row k="Network" v={simulated ? `${health.chain.name} (simulated)` : `${health.chain.name} (${health.chain.chain_id})`} />
          <Row k="Registry configured" v={health.chain.contract_configured ? "yes" : "no"} />
          <Row k="Last transaction" v={anchor?.tx_hash ? <span className="mono">{anchor.tx_hash.slice(0, 10)}…{anchor.tx_hash.slice(-6)}</span> : "–"} />
          <Row k="Block" v={anchor?.block_number ?? "–"} />
          <Row
            k="Explorer"
            v={anchor?.explorer_url ? <a href={anchor.explorer_url} target="_blank" rel="noreferrer noopener">open</a> : simulated && anchor ? "none (not a blockchain)" : "–"}
          />
        </dl>
      </section>
    </aside>
  );
}

const TL = ["Image upload", "Face analysis", "Web search", "Match verification", "Chain record"];
const MATCHERS = [/Reading input/, /Detecting/, /Reverse image/, /Confirming/, /Anchoring/];

/** Timeline from the pipeline's real stage list. A stage is 'done' once a later one has started. */
export function Timeline({ job }: { job: JobStatus | null }) {
  const reached = job ? MATCHERS.map((m) => job.stages.some((s) => m.test(s))) : TL.map(() => false);
  const last = reached.lastIndexOf(true);
  const finished = !!job && ["succeeded", "no_match", "failed", "cancelled"].includes(job.status);
  return (
    <section className="timeline card" aria-label="Verification timeline">
      <h2>Verification timeline</h2>
      <ol>
        {TL.map((label, i) => {
          let state = "Pending";
          if (reached[i]) state = i < last || (finished && i === last && job?.status === "succeeded") ? "Done" : finished ? "Stopped here" : "In progress";
          return (
            <li key={label} className={state === "Done" ? "done" : state === "Pending" ? "" : "active"}>
              <span className="n">{i + 1}</span>
              <b>{label}</b>
              <small>{state}</small>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
