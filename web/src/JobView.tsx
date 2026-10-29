import { useState } from "react";
import { api, type CandidateRow, type Health, type JobStatus, type VerifyReport } from "./api";
import { VerifyResult } from "./VerifyPanel";

const STATE_TEXT: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Registered",
  no_match: "No match",
  failed: "Failed",
  cancelling: "Cancelling (the running step must finish first)",
  cancelled: "Cancelled",
};

function evidenceLabel(rule: string): string {
  if (rule === "confirmed_face_match") return "Face match";
  if (rule === "confirmed_image_derivative") return "Image derivative (perceptual hash only - NOT a face match)";
  return rule;
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    confirmed_face_match: "Face match",
    confirmed_image_derivative: "Image derivative",
    rejected_low_similarity: "Rejected: low similarity",
    rejected_no_face_in_candidate: "Rejected: no face found",
    skipped_no_image_url: "Not checked: no image URL",
    skipped_download_failed: "Not checked: download failed",
    skipped_url_blocked: "Not checked: URL blocked by safety guard",
    skipped_analysis_failed: "Not checked: analysis failed",
  };
  return map[status] ?? status;
}

function CandidatesTable({ rows, chosen }: { rows: CandidateRow[]; chosen: string }) {
  if (rows.length === 0) return <p className="muted empty">No candidates were returned.</p>;
  return (
    <div className="scroll">
      <table>
        <caption>Every candidate the search returned, with its independently measured scores (rejections included)</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Domain</th>
            <th scope="col">Outcome</th>
            <th scope="col">Face cosine</th>
            <th scope="col">pHash distance</th>
            <th scope="col">Faces</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.page_url + i} className={r.page_url === chosen ? "chosen" : undefined}>
              <td>{i + 1}</td>
              <td title={r.page_url}>
                {r.domain || "?"}
                {r.page_url === chosen && <strong> (registered)</strong>}
              </td>
              <td>{statusLabel(r.status)}</td>
              <td>{r.face_similarity}</td>
              <td>{r.phash_distance >= 0 ? `${r.phash_distance}/64` : "-"}</td>
              <td>{r.faces_in_candidate}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function JobView({ job, health }: { job: JobStatus; health: Health }) {
  const [report, setReport] = useState<VerifyReport | null>(null);
  const [verifyError, setVerifyError] = useState("");
  const running = job.status === "queued" || job.status === "running" || job.status === "cancelling";
  const record = job.record;
  const match = record?.payload.match;

  async function verifyThisRecord() {
    setVerifyError("");
    setReport(null);
    try {
      const blob = await fetch(api.fileUrl(job.id, "verification.json")).then((r) => r.blob());
      const form = new FormData();
      form.set("record", blob, "verification.json");
      form.set("job_id", job.id);
      form.set("simulated", String(job.simulated_chain));
      setReport(await api.verify(form));
    } catch (e) {
      setVerifyError((e as Error).message);
    }
  }

  return (
    <div className="card">
      <h2>
        Status: <span className={`state ${job.status}`}>{STATE_TEXT[job.status] ?? job.status}</span>
      </h2>

      <ol className="stages" aria-label="Pipeline stages">
        {job.stages.map((s, i) => {
          const active = running && i === job.stages.length - 1;
          return (
            <li key={s + i} className={active ? "active" : "done"}>
              {s} <span className="muted">{active ? "(in progress)" : "(done)"}</span>
            </li>
          );
        })}
        {job.stages.length === 0 && <li className="muted">Waiting to start...</li>}
      </ol>

      {job.message && !running && (
        <p className={`banner ${job.status === "succeeded" ? "ok" : job.status === "no_match" ? "warn" : "error"}`} role="status">
          {job.message}
        </p>
      )}
      {job.simulated_chain && record && (
        <p className="banner warn">
          <strong>SIMULATED chain.</strong> The anchor is an entry in a local JSON file, not a blockchain transaction.
        </p>
      )}
      {record?.payload.test_mode && (
        <p className="banner warn">
          <strong>TEST-ONLY record.</strong> Made with a stub engine and/or offline fixture; it is not a real verification.
        </p>
      )}

      {job.candidates.length > 0 && <CandidatesTable rows={job.candidates} chosen={match?.matched_url ?? ""} />}

      {record && match && (
        <>
          <h3>Evidence</h3>
          <dl className="facts">
            <dt>Evidence type</dt>
            <dd>
              <strong>{evidenceLabel(match.decision_rule)}</strong>
            </dd>
            <dt>Matched post</dt>
            <dd className="wrap">{match.matched_url}</dd>
            <dt>Scores</dt>
            <dd>
              face cosine {match.face_similarity} (threshold {match.face_cosine_threshold}); pHash {match.phash_distance}/64 (max{" "}
              {match.phash_max_distance})
            </dd>
            <dt>Claim recorded</dt>
            <dd>{match.claim}</dd>
            <dt>Limitations</dt>
            <dd>
              <ul>
                {(match.limitations ?? []).map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </dd>
            <dt>Verification hash</dt>
            <dd className="mono wrap">{record.integrity.verification_hash}</dd>
            <dt>Integrity algorithm</dt>
            <dd className="mono">{record.integrity.algorithm}</dd>
            <dt>Anchor</dt>
            <dd>
              {record.anchor?.simulated ? "simulated" : record.anchor?.network} - block {record.anchor?.block_number}
              {record.anchor?.tx_hash && <span className="mono wrap"> - tx {record.anchor.tx_hash}</span>}
              {record.anchor?.explorer_url && (
                <>
                  {" "}
                  <a href={record.anchor.explorer_url} target="_blank" rel="noreferrer noopener">
                    explorer
                  </a>
                </>
              )}
            </dd>
          </dl>
          {job.artefacts.includes("comparison.png") && (
            <figure className="preview">
              <img src={api.fileUrl(job.id, "comparison.png")} alt="Query face beside the matched candidate face, with scores" />
              <figcaption className="muted">Comparison image written by the pipeline (face crops are local evidence).</figcaption>
            </figure>
          )}
          <h3>Downloads</h3>
          <ul className="links">
            {job.artefacts
              .filter((a) => a.endsWith(".json"))
              .map((a) => (
                <li key={a}>
                  <a href={api.fileUrl(job.id, a)} download={a}>
                    {a}
                  </a>
                </li>
              ))}
          </ul>
          {job.manifest && (
            <p className="muted">
              Evidence manifest: {job.manifest.file_count} files with SHA-256 digests. The manifest alone does not prove the bundle
              is unmodified; the sealed record commits to the key digests.
            </p>
          )}
          <button type="button" onClick={verifyThisRecord}>
            Verify this record now
          </button>
          {verifyError && (
            <p className="banner error" role="alert">
              {verifyError}
            </p>
          )}
          {report && <VerifyResult report={report} />}
        </>
      )}

      <details>
        <summary>Pipeline log ({job.log.length} lines)</summary>
        <pre className="log">{job.log.join("\n")}</pre>
      </details>
      <p className="muted">
        Thresholds in use: cosine {health.thresholds.face_cosine}, pHash {health.thresholds.phash_max_distance}. They depend on the
        model and data and are not calibrated for any population.
      </p>
    </div>
  );
}
