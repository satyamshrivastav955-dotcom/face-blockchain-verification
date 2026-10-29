import { useEffect, useState } from "react";
import { api, type Health } from "./api";
import { RegisterPanel } from "./RegisterPanel";
import { VerifyPanel } from "./VerifyPanel";

type Tab = "register" | "verify";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("register");

  useEffect(() => {
    api.health().then(setHealth).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>FaceProof</h1>
          <p className="tagline">Image-provenance evidence, computed locally. It is not an identity-recognition tool.</p>
        </div>
        <nav aria-label="Sections" className="tabs" role="tablist">
          {(["register", "verify"] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              className={tab === t ? "tab active" : "tab"}
              onClick={() => setTab(t)}
            >
              {t === "register" ? "Register provenance" : "Check a record"}
            </button>
          ))}
        </nav>
      </header>

      {error && (
        <div className="banner error" role="alert">
          Cannot reach the local API ({error}). Start it with <code>python -m src.web</code>.
        </div>
      )}
      {!health && !error && <p className="muted">Connecting to the local API...</p>}

      {health && (
        <>
          {health.demo_mode && (
            <div className="banner warn" role="status">
              <strong>DEMO MODE.</strong> The stub face engine and an offline synthetic fixture are enabled. Results are
              plumbing tests, not real verification.
            </div>
          )}
          {!health.models_present && !health.demo_mode && (
            <div className="banner warn" role="status">
              Face models are missing. Run <code>python scripts/fetch_models.py</code> first; real registrations will fail
              until then.
            </div>
          )}
          <main>{tab === "register" ? <RegisterPanel health={health} /> : <VerifyPanel health={health} />}</main>
        </>
      )}
      <footer className="muted">
        Local-first: this page talks only to <code>127.0.0.1</code>. A record shows what was measured and anchored, not that a
        claim is true.
      </footer>
    </div>
  );
}
