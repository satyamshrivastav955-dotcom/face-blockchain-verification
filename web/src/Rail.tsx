import type { Health, JobStatus } from "./api";
import { CountUp, Leader, Stamp } from "./ui";

const STATE_TEXT: Record<string, string> = {
  queued: "Queued",
  running: "Under examination",
  succeeded: "Filed",
  no_match: "No finding",
  failed: "Could not complete",
  cancelling: "Withdrawing",
  cancelled: "Withdrawn",
};

/** Case ledger. Every value is derived from the job or /api/health; an em dash means "not yet available". */
export function Ledger({ job, health }: { job: JobStatus | null; health: Health }) {
  const measured = job?.candidates.filter((c) => !c.status.startsWith("skipped")) ?? [];
  const best = measured.length ? Math.max(...measured.map((c) => parseFloat(c.face_similarity))) : null;
  const rec = job?.record;
  const anchor = rec?.anchor;
  const simulated = job ? job.simulated_chain : true;
  const rule = rec?.payload.match.decision_rule;

  return (
    <aside className="ledger-col" aria-label="Case ledger">
      <section className="ledger">
        <header>
          <h2>Case ledger</h2>
          {health.demo_mode && <span className="mini">DEMO</span>}
        </header>
        <Leader k="Status" v={job ? STATE_TEXT[job.status] ?? job.status : "—"} />
        <Leader k="Leads returned" v={job ? <CountUp value={job.candidates.length} /> : "—"} />
        <Leader k="Examined locally" v={job ? <CountUp value={measured.length} /> : "—"} />
        <Leader k="Highest face cosine" v={best !== null ? <CountUp value={best} decimals={4} /> : "—"} />
        <Leader k="Evidence" v={rule ? (rule === "confirmed_face_match" ? "Face match" : "Image derivative") : "—"} />
        <Leader k="Record" v={rec ? "sealed" : "—"} />
        {rule && (
          <div className="ledger-stamp">
            {rule === "confirmed_face_match" ? (
              <Stamp tone="ok" tilt={-7}>Face match</Stamp>
            ) : (
              <Stamp tone="warn" tilt={-7}>Image similarity only</Stamp>
            )}
          </div>
        )}
        {job && (job.status === "no_match" || job.status === "failed") && (
          <div className="ledger-stamp">
            <Stamp tone={job.status === "failed" ? "err" : "mute"} tilt={-6}>{job.status === "failed" ? "Not completed" : "No finding"}</Stamp>
          </div>
        )}
      </section>

      <section className="ledger">
        <header>
          <h2>Ledger of record</h2>
          <span className={`mini ${simulated ? "warn" : "ok"}`}>{simulated ? "SIMULATED" : "LIVE"}</span>
        </header>
        <Leader k="Network" v={simulated ? `${health.chain.name} (simulated)` : `${health.chain.name} · ${health.chain.chain_id}`} />
        <Leader k="Registry set" v={health.chain.contract_configured ? "yes" : "no"} />
        <Leader k="Transaction" v={anchor?.tx_hash ? <span className="mono">{anchor.tx_hash.slice(0, 10)}…{anchor.tx_hash.slice(-6)}</span> : "—"} />
        <Leader k="Block" v={anchor?.block_number ?? "—"} />
        <Leader
          k="Explorer"
          v={anchor?.explorer_url ? <a href={anchor.explorer_url} target="_blank" rel="noreferrer noopener">open</a> : simulated && anchor ? "none: not a blockchain" : "—"}
        />
      </section>
    </aside>
  );
}

const STEPS = ["Receive", "Analyse", "Search", "Re-examine", "Seal & file"];
const MATCHERS = [/Reading input/, /Detecting/, /Reverse image/, /Confirming/, /Anchoring/];

/** Chain-of-custody strip from the pipeline's real stage list. A step is 'done' once a later one has begun. */
export function Custody({ job }: { job?: JobStatus | null }) {
  const reached = job ? MATCHERS.map((m) => job.stages.some((s) => m.test(s))) : STEPS.map(() => false);
  const last = reached.lastIndexOf(true);
  const finished = !!job && ["succeeded", "no_match", "failed", "cancelled"].includes(job.status);
  return (
    <ol className="custody-strip" aria-label="Chain of custody">
      {STEPS.map((label, i) => {
        let state = "pending";
        if (reached[i]) state = i < last || (finished && i === last && job?.status === "succeeded") ? "done" : finished ? "stopped" : "active";
        return (
          <li key={label} className={state}>
            <span className="pip" aria-hidden="true">{state === "done" ? "✓" : i + 1}</span>
            <b>{label}</b>
            <small>{state === "done" ? "done" : state === "active" ? "in progress" : state === "stopped" ? "stopped here" : "pending"}</small>
          </li>
        );
      })}
    </ol>
  );
}
