import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Disclosure, type Health, type JobStatus } from "./api";
import { JobView } from "./JobView";

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

  return (
    <div className="grid">
      <form onSubmit={submit} className="card" aria-labelledby="reg-h">
        <h2 id="reg-h">1. Choose an image</h2>
        <label className="field">
          <span>Image file (JPEG, PNG, WebP, GIF or BMP, up to {Math.round(health.limits.upload_bytes / 1048576)} MiB)</span>
          <input type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={busy} />
        </label>
        {health.demo_mode && (
          <button type="button" className="secondary" onClick={useSample} disabled={busy}>
            Use the bundled synthetic sample
          </button>
        )}
        {previewUrl ? (
          <figure className="preview">
            <img src={previewUrl} alt="Preview of the selected image" />
            <figcaption className="muted">
              Previewed in your browser only. Face analysis runs on this machine; nothing is uploaded until you consent
              below.
            </figcaption>
          </figure>
        ) : (
          <p className="muted empty">No image selected.</p>
        )}

        <h2>2. Search provider and privacy</h2>
        <label className="field">
          <span>Reverse-image search provider</span>
          <select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={busy}>
            {providers.map((p) => (
              <option key={p} value={p}>
                {p === "local_fixture" ? "local_fixture (offline demo, no network)" : p}
              </option>
            ))}
          </select>
        </label>
        {disclosure && !disclosure.external && (
          <p className="note ok">Local only: no data leaves this machine for this provider.</p>
        )}
        {disclosure?.external && (
          <fieldset className="consent">
            <legend>This sends data to third parties</legend>
            <ul>
              {disclosure.items.map((i) => (
                <li key={i.flag}>
                  <strong>{i.service}</strong> receives: {i.what_is_sent}
                </li>
              ))}
            </ul>
            <p className="muted">
              No retention or deletion promise is made here; that is governed by each service&apos;s own terms.
            </p>
            <label className="check">
              <input type="checkbox" checked={consentSearch} onChange={(e) => setConsentSearch(e.target.checked)} />
              <span>I consent to the external search described above.</span>
            </label>
            {needsUploadConsent && (
              <label className="check">
                <input type="checkbox" checked={consentUpload} onChange={(e) => setConsentUpload(e.target.checked)} />
                <span>I consent to uploading this image to a public host.</span>
              </label>
            )}
            <label className="field">
              <span>Optional: URL of the image you host yourself (avoids any upload)</span>
              <input type="url" value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="https://..." />
            </label>
          </fieldset>
        )}

        <h2>3. Options</h2>
        <label className="check">
          <input type="checkbox" checked={simulate} disabled={!health.chain_writes_enabled || busy} onChange={(e) => setSimulate(e.target.checked)} />
          <span>
            Use the <strong>simulated</strong> local chain (a JSON file, not a blockchain)
            {!health.chain_writes_enabled && " - real-chain writes are disabled on this server"}
          </span>
        </label>
        <label className="check">
          <input type="checkbox" checked={requireFace} onChange={(e) => setRequireFace(e.target.checked)} disabled={busy} />
          <span>Only register a face match (exclude image-similarity-only results)</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={minimal} onChange={(e) => setMinimal(e.target.checked)} disabled={busy} />
          <span>Minimal evidence (do not save face crops or downloaded image bytes)</span>
        </label>

        {error && (
          <p className="banner error" role="alert">
            {error}
          </p>
        )}
        <div className="row">
          <button type="submit" disabled={!file || busy || !consentOk}>
            {busy ? "Running..." : "Start verification"}
          </button>
          {busy && (
            <button type="button" className="secondary" onClick={cancel}>
              Cancel
            </button>
          )}
        </div>
        {!consentOk && <p className="muted">Tick the consent box(es) above to enable the external search.</p>}
      </form>

      <section aria-live="polite" aria-label="Result">
        {job ? <JobView job={job} health={health} /> : <p className="muted empty card">Results appear here once a run starts.</p>}
      </section>
    </div>
  );
}
