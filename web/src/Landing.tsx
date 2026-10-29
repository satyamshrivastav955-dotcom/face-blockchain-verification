import type { Health } from "./api";

const STEPS = [
  { n: "01", t: "Detect", d: "YuNet finds the face and SFace computes an embedding. Local CPU; nothing leaves the machine.", tag: "LOCAL" },
  { n: "02", t: "Search", d: "A reverse-image provider returns candidate pages. Leads only, never trusted. Needs your consent.", tag: "THIRD PARTY" },
  { n: "03", t: "Re-check", d: "Each candidate is downloaded behind an SSRF guard, re-analysed, and scored twice: face cosine and perceptual hash.", tag: "LOCAL" },
  { n: "04", t: "Seal", d: "A deterministic record is hashed with SHA-256 over restricted RFC 8785 canonical JSON.", tag: "LOCAL" },
  { n: "05", t: "Anchor", d: "Only the hash and a keccak256 URL commitment go on-chain. Never a face, a vector or a URL.", tag: "ON-CHAIN" },
];

export function Landing({ health }: { health: Health | null }) {
  return (
    <div className="landing">
      <section className="hero">
        <p className="eyebrow">Image provenance · not identity recognition</p>
        <h1>
          Evidence of <em>where</em> an image appeared.
          <br />
          Never a claim about <em>who</em> is in it.
        </h1>
        <p className="lede">
          FaceProof re-checks every search lead on your own machine, tells you honestly whether the evidence is a face match or only an
          image-similarity match, and anchors a tamper-evident hash of the result without publishing the face, the embedding or the URL.
        </p>
        <div className="cta">
          <a className="btn primary" href="#/verify">Register provenance</a>
          <a className="btn" href="#/record">Check an existing record</a>
        </div>
        <dl className="hero-meta" aria-label="Live configuration">
          <div>
            <dt>Face threshold</dt>
            <dd>{health ? health.thresholds.face_cosine : "–"}</dd>
          </div>
          <div>
            <dt>pHash max distance</dt>
            <dd>{health ? `${health.thresholds.phash_max_distance} / 64` : "–"}</dd>
          </div>
          <div>
            <dt>Models</dt>
            <dd>{health ? (health.models_present ? "present" : "missing") : "–"}</dd>
          </div>
          <div>
            <dt>Chain</dt>
            <dd>{health ? `${health.chain.name} (${health.chain.chain_id})` : "–"}</dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="flow-h" className="block">
        <h2 id="flow-h">Five stages, each labelled by where it runs</h2>
        <ol className="flow">
          {STEPS.map((s) => (
            <li key={s.n}>
              <span className="num">{s.n}</span>
              <h3>{s.t}</h3>
              <p>{s.d}</p>
              <span className={`tag ${s.tag === "LOCAL" ? "local" : s.tag === "ON-CHAIN" ? "chain" : "ext"}`}>{s.tag}</span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="two-h" className="block two">
        <div>
          <h2 id="two-h">Two kinds of evidence, never blurred</h2>
          <p className="muted-lg">
            Perceptual hashing finds resized or re-encoded copies. It says nothing about faces. So a candidate is accepted under exactly one label.
          </p>
        </div>
        <div className="evidence-pair">
          <article>
            <h3>Face match</h3>
            <p>A face in the candidate scored at or above the threshold against the query face. A similarity measurement, not an identity statement.</p>
          </article>
          <article className="alt">
            <h3>Image derivative</h3>
            <p>
              Perceptually similar image; <strong>the face test did not pass</strong>. Recorded and displayed as image similarity only.
            </p>
          </article>
        </div>
      </section>

      <section aria-labelledby="proof-h" className="block two">
        <div>
          <h2 id="proof-h">What a record can and cannot show</h2>
        </div>
        <div className="ledger">
          <div>
            <h3>Can show</h3>
            <ul>
              <li>The pipeline measured these scores for this candidate.</li>
              <li>The record is unchanged since it was sealed.</li>
              <li>This hash was registered at a block and time.</li>
              <li>The on-chain URL commitment matches the record.</li>
            </ul>
          </div>
          <div>
            <h3>Cannot show</h3>
            <ul>
              <li>That the claim is true.</li>
              <li>That the page is authentic or who published it.</li>
              <li>Who a person in an image is.</li>
              <li>Anything, if a required check could not run: that result is <em>inconclusive</em>.</li>
            </ul>
          </div>
        </div>
      </section>

      <section aria-labelledby="priv-h" className="block two">
        <div>
          <h2 id="priv-h">Consent before anything leaves your machine</h2>
          <p className="muted-lg">External search and public upload are opt-in, per run, with the exact data flow shown first.</p>
        </div>
        <ul className="rules">
          <li><b>Local</b> face analysis, hashing, sealing, local verification, the offline demo.</li>
          <li><b>Opt-in</b> search provider, optional public image host, candidate hosts, RPC node.</li>
          <li><b>Never</b> embeddings, face crops or plaintext URLs on-chain.</li>
          <li><b>Simulated</b> chain is a JSON file and is labelled that way everywhere.</li>
        </ul>
      </section>

      <section className="closing">
        <h2>Start with a real run, or rehearse offline.</h2>
        <div className="cta">
          <a className="btn primary" href="#/verify">Open the workspace</a>
          <a className="btn" href="#/system">Inspect system status</a>
        </div>
      </section>
    </div>
  );
}
