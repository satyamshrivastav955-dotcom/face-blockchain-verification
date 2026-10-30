import { useState } from "react";
import { api, type CandidateRow, type Health, type JobStatus, type VerifyReport } from "./api";
import { Reveal, Seal, Stamp } from "./ui";
import { VerifyResult } from "./VerifyPanel";

const STATE_TEXT: Record<string, string> = {
  queued: "Queued",
  running: "Under examination",
  succeeded: "Filed",
  no_match: "No finding",
  failed: "Could not be completed",
  cancelling: "Withdrawing (the running step must finish first)",
  cancelled: "Withdrawn",
};

const STATUS_LABEL: Record<string, { text: string; tone: "ok" | "warn" | "err" | "mute" }> = {
  confirmed_face_match: { text: "Face match", tone: "ok" },
  confirmed_image_derivative: { text: "Image derivative", tone: "warn" },
  rejected_low_similarity: { text: "Rejected · low similarity", tone: "err" },
  rejected_no_face_in_candidate: { text: "Rejected · no face found", tone: "err" },
  skipped_no_image_url: { text: "Not examined · no image URL", tone: "mute" },
  skipped_download_failed: { text: "Not examined · download failed", tone: "mute" },
  skipped_url_blocked: { text: "Not examined · blocked by safety guard", tone: "mute" },
  skipped_analysis_failed: { text: "Not examined · analysis failed", tone: "mute" },
};

function Schedule({ rows, chosen }: { rows: CandidateRow[]; chosen: string }) {
  if (rows.length === 0) return <p className="empty">The provider returned no candidates.</p>;
  return (
    <div className="scroll">
      <table className="schedule">
        <caption>Schedule of candidates: every lead the search returned, with its independently measured scores. Rejections are kept.</caption>
        <thead>
          <tr>
            <th scope="col">No.</th>
            <th scope="col">Source</th>
            <th scope="col">Outcome</th>
            <th scope="col" className="num">Cosine</th>
            <th scope="col" className="num">pHash</th>
            <th scope="col" className="num">Faces</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const s = STATUS_LABEL[r.status] ?? { text: r.status, tone: "mute" as const };
            return (
              <tr key={r.page_url + i} className={r.page_url === chosen ? "chosen" : undefined}>
                <td className="mono">{String(i + 1).padStart(2, "0")}</td>
                <td title={r.page_url}>
                  {r.domain || "?"}
                  {r.page_url === chosen && <b className="filed"> · filed</b>}
                </td>
                <td><span className={`outcome ${s.tone}`}>{s.text}</span></td>
                <td className="num mono">{r.face_similarity}</td>
                <td className="num mono">{r.phash_distance >= 0 ? `${r.phash_distance}/64` : "—"}</td>
                <td className="num mono">{r.faces_in_candidate}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function JobView({ job, health }: { job: JobStatus; health: Health }) {
  const [report, setReport] = useState<VerifyReport | null>(null);
  const [verifyError, setVerifyError] = useState("");
  const [verifying, setVerifying] = useState(false);
  const running = job.status === "queued" || job.status === "running" || job.status === "cancelling";
  const record = job.record;
  const match = record?.payload.match;
  const isFace = match?.decision_rule === "confirmed_face_match";

  async function verifyThisRecord() {
    setVerifyError("");
    setReport(null);
    setVerifying(true);
    try {
      const blob = await fetch(api.fileUrl(job.id, "verification.json")).then((r) => r.blob());
      const form = new FormData();
      form.set("record", blob, "verification.json");
      form.set("job_id", job.id);
      form.set("simulated", String(job.simulated_chain));
      setReport(await api.verify(form));
    } catch (e) {
      setVerifyError((e as Error).message);
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="jobview">
      <header className="f-head">
        <h2>Proceedings</h2>
        <span className={`state ${job.status}`}>{STATE_TEXT[job.status] ?? job.status}</span>
      </header>

      <ol className="proceedings" aria-label="Pipeline stages">
        {job.stages.map((s, i) => {
          const active = running && i === job.stages.length - 1;
          return (
            <li key={s + i} className={active ? "active" : "done"}>
              <span>{s}</span>
              <i aria-hidden="true" />
              <em>{active ? "in progress" : "done"}</em>
            </li>
          );
        })}
        {job.stages.length === 0 && <li className="muted">Waiting to start…</li>}
      </ol>

      {job.message && !running && (
        <p className={`notice ${job.status === "succeeded" ? "ok" : job.status === "no_match" ? "warn" : "err"}`} role="status">{job.message}</p>
      )}
      {job.simulated_chain && record && (
        <p className="notice warn"><b>Simulated ledger.</b> The anchor is an entry in a local JSON file, not a blockchain transaction.</p>
      )}
      {record?.payload.test_mode && (
        <p className="notice warn"><b>Test-only record.</b> Made with a stub engine and/or offline fixture; it is not a real verification.</p>
      )}

      {job.candidates.length > 0 && (
        <Reveal><Schedule rows={job.candidates} chosen={match?.matched_url ?? ""} /></Reveal>
      )}

      {record && match && (
        <Reveal>
          <section className="finding-sheet" aria-label="Finding">
            <div className="fs-top">
              <div>
                <p className="folio">Finding</p>
                <h2>{isFace ? "Face match" : "Image derivative"}</h2>
                {!isFace && <p className="warnline">Perceptual-hash similarity only. The face test did <b>not</b> confirm a match.</p>}
              </div>
              <div className="fs-marks">
                <Seal />
                <Stamp tone={isFace ? "ok" : "warn"} big tilt={-8} delay={350}>{isFace ? "Face match" : "Image similarity only"}</Stamp>
              </div>
            </div>

            <dl className="facts">
              <dt>Matched post</dt>
              <dd className="wrap">{match.matched_url}</dd>
              <dt>Scores</dt>
              <dd>face cosine {match.face_similarity} (threshold {match.face_cosine_threshold}) · pHash {match.phash_distance}/64 (limit {match.phash_max_distance})</dd>
              <dt>Statement</dt>
              <dd>{match.claim}</dd>
              <dt>Reservations</dt>
              <dd>
                <ul>{(match.limitations ?? []).map((l) => <li key={l}>{l}</li>)}</ul>
              </dd>
              <dt>Engine</dt>
              <dd>
                {record.payload.face.engine}
                {record.payload.face.model_license && <span className="muted"> · {record.payload.face.model_license}</span>}
              </dd>
              {!isFace && match.derivative_basis && (
                <>
                  <dt>Derivative basis</dt>
                  <dd>
                    {match.derivative_basis}
                    {(match.geometric_inliers ?? 0) > 0 && ` · ${match.geometric_inliers} of ${match.geometric_matches} local features agree on one transform`}
                  </dd>
                </>
              )}
              {record.payload.source_image?.content_credentials && (
                <>
                  <dt>Content credentials</dt>
                  <dd>
                    {record.payload.source_image.content_credentials.state}
                    {record.payload.source_image.content_credentials.state === "valid" && record.payload.source_image.content_credentials.untrusted_signer && " (signer not on a trust list)"}
                    {record.payload.source_image.content_credentials.ai_generated && " · declares AI-generated"}
                  </dd>
                </>
              )}
              <dt>Seal</dt>
              <dd className="mono wrap">{record.integrity.verification_hash}<br /><span className="muted">{record.integrity.algorithm}</span></dd>
              <dt>Anchor</dt>
              <dd>
                {record.anchor?.simulated ? "simulated ledger" : record.anchor?.network} · block {record.anchor?.block_number}
                {record.anchor?.tx_hash && <span className="mono wrap"> · tx {record.anchor.tx_hash}</span>}
                {record.anchor?.explorer_url && (<> · <a href={record.anchor.explorer_url} target="_blank" rel="noreferrer noopener">explorer</a></>)}
              </dd>
            </dl>

            {job.artefacts.includes("comparison.png") && (
              <figure className="print">
                <img src={api.fileUrl(job.id, "comparison.png")} alt="Query face beside the matched candidate face, with scores" />
                <figcaption>Plate 1 · comparison written by the pipeline. Face crops are local evidence.</figcaption>
              </figure>
            )}

            <h3>Annexes</h3>
            <ul className="annexes">
              {job.artefacts.filter((a) => a.endsWith(".json")).map((a) => (
                <li key={a}><a href={api.fileUrl(job.id, a)} download={a}>{a}</a></li>
              ))}
            </ul>
            {job.manifest && (
              <p className="muted">
                Manifest lists {job.manifest.file_count} files with SHA-256 digests. A manifest alone does not prove the bundle is unmodified; the sealed record commits to the key digests.
              </p>
            )}
            <button type="button" className="btn solid" onClick={verifyThisRecord} disabled={verifying}>{verifying ? "Examining record…" : "Examine this record now"}</button>
            {verifyError && <p className="notice err" role="alert">{verifyError}</p>}
            {report && <VerifyResult report={report} />}
          </section>
        </Reveal>
      )}

      <details className="log-box">
        <summary>Pipeline log ({job.log.length} lines)</summary>
        <pre className="log">{job.log.join("\n")}</pre>
      </details>
      <p className="muted">
        Thresholds in force: cosine {health.thresholds.face_cosine}, pHash {health.thresholds.phash_max_distance}. They depend on the model and data and are not calibrated for any population.
      </p>
    </div>
  );
}
