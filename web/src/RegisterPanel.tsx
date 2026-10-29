import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Disclosure, type Health, type JobStatus } from "./api";
import { JobView } from "./JobView";
import { Custody, Ledger } from "./Rail";

const TERMINAL = ["succeeded", "no_match", "failed", "cancelled"];

export function RegisterPanel({ health }: { health: Health }) {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [provider, setProvider] = useState(health.demo_mode ? "local_fixture" : health.search_provider);
  const [disclosure, setDisclosure] = useState<Disclosure | null>(null);
  const [consentSearch, setConsentSearch] = useState(false);
  const [consentUpload, setConsentUpload] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [simulate, setSimulate] = useState(true);
  const [requireFace, setRequireFace] = useState(false);
  const [minimal, setMinimal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [job, setJob] = useState<JobStatus | null>(null);
  const [dragging, setDragging] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const providers = health.demo_mode ? ["local_fixture", "serpapi_lens", "tineye"] : ["serpapi_lens", "tineye"];

  useEffect(() => {
    if (!file) return setPreviewUrl("");
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    setConsentSearch(false);
    setConsentUpload(false);
    api.disclosure(provider).then(setDisclosure).catch(() => setDisclosure(null));
  }, [provider]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const needsSearchConsent = disclosure?.external === true;
  const needsUploadConsent = !!disclosure?.items.some((i) => i.flag === "--consent-public-upload") && !imageUrl.trim();
  const consentOk = (!needsSearchConsent || consentSearch) && (!needsUploadConsent || consentUpload);

  function poll(id: string) {
    api
      .job(id)
      .then((j) => {
        setJob(j);
        if (!TERMINAL.includes(j.status)) timer.current = window.setTimeout(() => poll(id), 700);
        else setBusy(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setBusy(false);
      });
  }

  async function useSample() {
    try {
      const blob = await api.demoSample();
      setFile(new File([blob], "synthetic-sample.png", { type: "image/png" }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    if (!file) return;
    setError("");
    setBusy(true);
    setJob(null);
    const form = new FormData();
    form.set("image", file);
    form.set("provider", provider);
    form.set("simulate_chain", String(simulate));
    form.set("consent_external_search", String(consentSearch));
    form.set("consent_public_upload", String(consentUpload));
    form.set("require_face_match", String(requireFace));
    form.set("minimal_evidence", String(minimal));
    form.set("image_url", imageUrl.trim());
    form.set("use_demo_engine", String(health.demo_mode));
    try {
      const created = await api.createJob(form);
      poll(created.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "request failed");
      setBusy(false);
    }
  }

  async function cancel() {
    if (!job) return;
    window.clearTimeout(timer.current);
    try {
      await api.deleteJob(job.id);
      setJob(null);
      setBusy(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function onDrop(ev: React.DragEvent) {
    ev.preventDefault();
    setDragging(false);
    const f = ev.dataTransfer.files?.[0];
    if (f && !busy) setFile(f);
  }

  const caseNo = job ? `FP-${job.id.slice(0, 8).toUpperCase()}` : "FP-········";

  return (
    <div className="casefile">
      <header className="case-head">
        <p className="folio">Case file · {caseNo}</p>
        <h1 className="h1">Open a case</h1>
        <p className="lede">
          Mount an image. Faces are analysed here, every search lead is re-examined here, and the result is sealed. It measures provenance and never
          identifies a person.
        </p>
        <Custody job={job} />
      </header>

      <div className="case-grid">
        <div className="case-main">
          <form onSubmit={submit} aria-label="New case">
            <section className="plate" aria-labelledby="ex-a">
              <h2 id="ex-a"><span className="tag-ex">Exhibit A</span> The image under examination</h2>
              <div className="intake">
                <label
                  className={`mount${dragging ? " over" : ""}${previewUrl ? " has" : ""}`}
                  onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={onDrop}
                >
                  <input type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={busy} />
                  <i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
                  {previewUrl ? (
                    <img src={previewUrl} alt="Preview of the selected image" />
                  ) : (
                    <span className="mount-empty">
                      <b>Drop the image here</b>
                      <span>or click to choose a file</span>
                      <small>JPEG · PNG · WebP · GIF · BMP — up to {Math.round(health.limits.upload_bytes / 1048576)} MiB</small>
                    </span>
                  )}
                </label>
                <div className="caption-plate">
                  <h3>Label</h3>
                  <dl>
                    <div><dt>File</dt><dd>{file ? file.name : "—"}</dd></div>
                    <div><dt>Size</dt><dd>{file ? `${(file.size / 1024).toFixed(0)} KiB` : "—"}</dd></div>
                    <div><dt>Held</dt><dd>in your browser until you submit</dd></div>
                  </dl>
                  {health.demo_mode && (
                    <button type="button" className="link" onClick={useSample} disabled={busy}>Mount the synthetic sample</button>
                  )}
                </div>
              </div>
            </section>

            <section className="plate" aria-labelledby="ex-b">
              <h2 id="ex-b"><span className="tag-ex">Notice</span> Disclosure and consent</h2>
              <label className="field">
                <span>Reverse-image search provider</span>
                <select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={busy}>
                  {providers.map((p) => (
                    <option key={p} value={p}>{p === "local_fixture" ? "local_fixture — offline demonstration, no network" : p}</option>
                  ))}
                </select>
              </label>
              {disclosure && !disclosure.external && <p className="clear">Nothing leaves this machine for this provider.</p>}
              {disclosure?.external && (
                <fieldset className="disclosure">
                  <legend>Data will be sent to third parties</legend>
                  <ul>
                    {disclosure.items.map((i) => (
                      <li key={i.flag}><b>{i.service}</b> receives {i.what_is_sent}.</li>
                    ))}
                  </ul>
                  <p className="muted">No retention or deletion promise is made here; each service&apos;s own terms govern.</p>
                  <label className="check"><input type="checkbox" checked={consentSearch} onChange={(e) => setConsentSearch(e.target.checked)} /><span>I consent to the external search described above.</span></label>
                  {needsUploadConsent && (
                    <label className="check"><input type="checkbox" checked={consentUpload} onChange={(e) => setConsentUpload(e.target.checked)} /><span>I consent to uploading this image to a public host.</span></label>
                  )}
                  <label className="field">
                    <span>Or give a link to an image you host yourself (no upload)</span>
                    <input type="url" value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="https://…" />
                  </label>
                </fieldset>
              )}
            </section>

            <section className="plate" aria-labelledby="ex-c">
              <h2 id="ex-c"><span className="tag-ex">Terms</span> Instructions to the bureau</h2>
              <label className="check">
                <input type="checkbox" checked={simulate} disabled={!health.chain_writes_enabled || busy} onChange={(e) => setSimulate(e.target.checked)} />
                <span>File on the <b>simulated</b> ledger (a JSON file, not a blockchain){!health.chain_writes_enabled && " — real-chain writes are disabled on this server"}</span>
              </label>
              <label className="check"><input type="checkbox" checked={requireFace} onChange={(e) => setRequireFace(e.target.checked)} disabled={busy} /><span>Accept a face match only; refuse image-similarity-only findings</span></label>
              <label className="check"><input type="checkbox" checked={minimal} onChange={(e) => setMinimal(e.target.checked)} disabled={busy} /><span>Minimal evidence: keep no face crops or downloaded image bytes</span></label>

              {error && <p className="notice err" role="alert">{error}</p>}
              <div className="row">
                <button type="submit" className="btn solid" disabled={!file || busy || !consentOk}>{busy ? "Examining…" : "Begin examination"}</button>
                {busy && <button type="button" className="btn" onClick={cancel}>Withdraw</button>}
              </div>
              {!consentOk && <p className="muted">Tick the consent above to enable the external search.</p>}
            </section>
          </form>

          <section aria-live="polite" aria-label="Findings" className="findings-area">
            {job ? <JobView job={job} health={health} /> : <p className="empty">The schedule of candidates, findings and sealed record will be filed here.</p>}
          </section>
        </div>

        <Ledger job={job} health={health} />
      </div>
    </div>
  );
}
