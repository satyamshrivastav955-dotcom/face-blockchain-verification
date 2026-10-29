import type { Health } from "./api";
import { Leader, Reveal, Seal, Stamp } from "./ui";

const PROCEDURE = [
  { n: "1", t: "Detect", where: "LOCAL", d: "YuNet finds the face and SFace turns it into a 128-number embedding. It is computed on this machine and is never saved, sent or written on-chain." },
  { n: "2", t: "Search", where: "WITH CONSENT", d: "A reverse-image provider returns candidate pages. They are leads, never findings. Nothing is sent until you tick the box that names what is sent and to whom." },
  { n: "3", t: "Re-examine", where: "LOCAL", d: "Each lead is downloaded behind an SSRF guard, analysed again, and scored twice: face similarity and perceptual hash. Rejections are kept in the schedule." },
  { n: "4", t: "Seal", where: "LOCAL", d: "The result becomes a deterministic record, canonicalised (a restricted RFC 8785 profile) and hashed with SHA-256." },
  { n: "5", t: "Anchor", where: "ON-CHAIN", d: "Only that hash and a keccak256 commitment of the URL are registered. Never a face, a vector, an image or the URL itself." },
];

const REFUSED = [
  "This photograph shows a particular person.",
  "The claim made in the record is true.",
  "The web page is authentic, or who published it.",
  "A result, when a required check could not be run.",
];
const ATTESTED = [
  "The pipeline measured these scores for this candidate.",
  "The record is unchanged since it was sealed.",
  "This hash was registered at a block and time.",
  "The on-chain URL commitment matches the record.",
];

export function Landing({ health }: { health: Health | null }) {
  return (
    <div className="landing">
      {/* ------------------------------------------------ hero */}
      <section className="hero">
        <div className="hero-copy">
          <p className="folio">File no. FP-001 · Image provenance</p>
          <h1>
            The receipts for <em>where</em> an image appeared.
          </h1>
          <p className="lede">
            FaceProof re-examines every search lead on your own machine, says plainly whether the evidence is a <b>face match</b> or only an{" "}
            <b>image-similarity</b> match, and anchors a tamper-evident hash of the result. It publishes no face, no embedding and no URL.
          </p>
          <div className="cta">
            <a className="btn solid" href="#/verify">Open a case</a>
            <a className="btn" href="#/record">Examine a record</a>
          </div>
          <p className="fine">Not an identity tool. It cannot tell you who anyone is, and it will say so on every page.</p>
        </div>

        <div className="dossier" aria-label="Anatomy of a record (field names, no data)">
          <div className="sheet-back s2" aria-hidden="true" />
          <div className="sheet-back s1" aria-hidden="true" />
          <article className="sheet-front">
            <header>
              <span>RECORD · faceverify/v2</span>
              <span>Anatomy</span>
            </header>
            <Leader k="evidence_type" v="face_match | image_derivative" />
            <Leader k="decision_rule" v="named, never implied" />
            <Leader k="scores" v="cosine · pHash, as strings" />
            <Leader k="claim" v="worded per evidence type" />
            <Leader k="limitations" v="listed in the record" />
            <Leader k="embedding" v="commitment only, never the vector" />
            <Leader k="integrity" v="sha256 · restricted JCS" />
            <Leader k="anchor" v="hash + keccak256(url)" />
            <p className="legend">Illustrative layout: field names and allowed values only. A real record holds your run&apos;s data.</p>
            <div className="seal-wrap"><Seal /></div>
            <div className="stamp-pos"><Stamp tone="ok" big tilt={-9} delay={500}>Sealed</Stamp></div>
          </article>
        </div>
      </section>

      {/* ------------------------------------------------ instruments */}
      <Reveal>
        <section className="instruments" aria-label="Live bureau readings">
          <div><small>Face threshold</small><b>{health ? health.thresholds.face_cosine : "–"}</b></div>
          <div><small>pHash limit</small><b>{health ? `${health.thresholds.phash_max_distance} / 64` : "–"}</b></div>
          <div><small>Models</small><b>{health ? (health.models_present ? "on file" : "missing") : "–"}</b></div>
          <div><small>Registry</small><b>{health ? (health.chain.contract_configured ? "configured" : "not set") : "–"}</b></div>
          <div><small>Chain</small><b>{health ? health.chain.name : "–"}</b></div>
        </section>
      </Reveal>

      {/* ------------------------------------------------ procedure */}
      <section className="part" aria-labelledby="proc-h">
        <Reveal>
          <p className="folio">Part I</p>
          <h2 id="proc-h">Procedure</h2>
          <p className="part-lede">Five steps, each marked with where it runs. Two of them can send data to others; both ask first.</p>
        </Reveal>
        <ol className="procedure">
          {PROCEDURE.map((s, i) => (
            <li key={s.n}>
              <Reveal delay={i * 60}>
                <div className="proc-row">
                  <span className="proc-n">{s.n}</span>
                  <div>
                    <h3>{s.t}</h3>
                    <p>{s.d}</p>
                  </div>
                  <span className={`where ${s.where === "LOCAL" ? "local" : s.where === "ON-CHAIN" ? "chain" : "ext"}`}>{s.where}</span>
                </div>
              </Reveal>
            </li>
          ))}
        </ol>
      </section>

      {/* ------------------------------------------------ exhibits */}
      <section className="part" aria-labelledby="ex-h">
        <Reveal>
          <p className="folio">Part II</p>
          <h2 id="ex-h">Two kinds of evidence, never confused</h2>
          <p className="part-lede">
            Perceptual hashing finds resized or re-encoded copies and says nothing about faces. So every accepted candidate carries exactly one label.
          </p>
        </Reveal>
        <div className="exhibits">
          <Reveal>
            <article className="exhibit">
              <span className="ex-tag">Exhibit A</span>
              <h3>Face match</h3>
              <p>A face in the candidate scored at or above the threshold against the query face. A similarity measurement, never an identity statement.</p>
              <div className="ex-stamp"><Stamp tone="ok" tilt={-6}>Face match</Stamp></div>
            </article>
          </Reveal>
          <Reveal delay={90}>
            <article className="exhibit hatch">
              <span className="ex-tag">Exhibit B</span>
              <h3>Image derivative</h3>
              <p>
                Perceptually similar image, but <b>the face test did not pass</b>. Recorded and shown as image similarity only, and it can be excluded with one switch.
              </p>
              <div className="ex-stamp"><Stamp tone="warn" tilt={5}>Not a face match</Stamp></div>
            </article>
          </Reveal>
        </div>
      </section>

      {/* ------------------------------------------------ findings */}
      <section className="part" aria-labelledby="fi-h">
        <Reveal>
          <p className="folio">Part III</p>
          <h2 id="fi-h">What the file will and will not say</h2>
        </Reveal>
        <div className="findings">
          <Reveal>
            <div className="col refuse">
              <h3>Findings we refuse to make</h3>
              <ul>
                {REFUSED.map((r) => (
                  <li key={r}><s>{r}</s></li>
                ))}
              </ul>
              <p className="note">If a required check cannot run, the result is <b>inconclusive</b>, not a pass.</p>
            </div>
          </Reveal>
          <Reveal delay={90}>
            <div className="col attest">
              <h3>What a record can attest</h3>
              <ul>
                {ATTESTED.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ------------------------------------------------ custody */}
      <section className="part" aria-labelledby="cu-h">
        <Reveal>
          <p className="folio">Part IV</p>
          <h2 id="cu-h">Chain of custody</h2>
          <p className="part-lede">What stays here, what leaves with your consent, and the only thing that goes on the public ledger.</p>
        </Reveal>
        <Reveal>
          <div className="custody">
            <div>
              <h3>Stays on this machine</h3>
              <ul><li>Face detection and embeddings</li><li>Candidate re-checking</li><li>Hashing and sealing</li><li>Local verification</li><li>The offline demonstration</li></ul>
            </div>
            <div>
              <h3>Leaves only with consent</h3>
              <ul><li>Search provider: image or public link</li><li>Optional public image host</li><li>Candidate sites you download from</li><li>The RPC node you query</li></ul>
            </div>
            <div>
              <h3>Goes on-chain</h3>
              <ul><li>32-byte payload hash</li><li>32-byte URL commitment</li><li className="never">Never a face, vector or URL</li></ul>
            </div>
          </div>
        </Reveal>
      </section>

      {/* ------------------------------------------------ close */}
      <Reveal>
        <section className="closing">
          <div>
            <h2>Open a case, or rehearse offline.</h2>
            <p>Run the whole procedure on a synthetic fixture with no network, no key and no gas. Every simulated step is labelled as simulated.</p>
          </div>
          <div className="cta">
            <a className="btn solid inv" href="#/verify">Open a case</a>
            <a className="btn inv" href="#/system">Bureau status</a>
          </div>
        </section>
      </Reveal>
    </div>
  );
}
