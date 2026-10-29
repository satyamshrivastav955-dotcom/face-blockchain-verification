import { useEffect, useState } from "react";
import { api, type Health } from "./api";
import { Landing } from "./Landing";
import { RegisterPanel } from "./RegisterPanel";
import { SystemPanel } from "./SystemPanel";
import { InkFilters } from "./ui";
import { VerifyPanel } from "./VerifyPanel";

type Route = "home" | "verify" | "record" | "system";

const TABS: { route: Route; label: string; hash: string; no: string }[] = [
  { route: "home", label: "Overview", hash: "#/", no: "I" },
  { route: "verify", label: "Open a case", hash: "#/verify", no: "II" },
  { route: "record", label: "Examine a record", hash: "#/record", no: "III" },
  { route: "system", label: "Bureau status", hash: "#/system", no: "IV" },
];

function routeFromHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  return (["verify", "record", "system"] as Route[]).includes(h as Route) ? (h as Route) : "home";
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [route, setRoute] = useState<Route>(routeFromHash());

  useEffect(() => {
    const on = () => {
      setRoute(routeFromHash());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch((e: Error) => setError(e.message));
  }, []);

  const wait = !health && !error ? <p className="muted pad">Connecting to the local bureau...</p> : null;

  return (
    <div className="desk">
      <InkFilters />
      <a className="skip" href="#main">Skip to content</a>

      <header className="masthead">
        <div className="mast-row">
          <a className="wordmark" href="#/" aria-label="FaceProof, home">
            <span className="wm-mark" aria-hidden="true">
              <svg viewBox="0 0 32 32" width="30" height="30" fill="none" stroke="currentColor" strokeWidth="1.6">
                <rect x="4" y="3" width="24" height="26" rx="1.5" />
                <path d="M9 10h14M9 15h14M9 20h8" />
                <circle cx="23" cy="23" r="5" fill="var(--paper)" />
                <path d="M20.6 23.2l1.8 1.8 3-3.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className="wm-text">Face<b>Proof</b></span>
          </a>
          <p className="mast-note">Image provenance, kept on file. Never identity.</p>
          <span className={`status-tag ${health ? "ok" : error ? "bad" : ""}`} role="status">
            <i aria-hidden="true" />
            {health ? "Bureau online" : error ? "Bureau unreachable" : "Connecting"}
          </span>
        </div>
        <nav className="folders" aria-label="Sections">
          {TABS.map((t) => (
            <a key={t.route} href={t.hash} className={route === t.route ? "folder active" : "folder"} aria-current={route === t.route ? "page" : undefined}>
              <span className="fno">{t.no}</span>
              {t.label}
            </a>
          ))}
        </nav>
      </header>

      <main id="main" className="sheet">
        {error && (
          <div className="notice err" role="alert">
            <b>Bureau unreachable.</b> {error}. Start the local server with <code>python -m src.web</code>.
          </div>
        )}
        {health?.demo_mode && (
          <div className="notice warn" role="status">
            <b>Demonstration mode.</b> A stub face engine and a synthetic fixture are switched on. Findings are plumbing tests, not real verification.
          </div>
        )}
        {route === "home" && <Landing health={health} />}
        {route === "verify" && (health ? <RegisterPanel health={health} /> : wait)}
        {route === "record" && (health ? <VerifyPanel health={health} /> : wait)}
        {route === "system" && (health ? <SystemPanel health={health} /> : wait)}
      </main>

      <footer className="colophon">
        <span>FaceProof · local-first image provenance</span>
        <span>A record shows what was measured and anchored, not that a claim is true. It never identifies a person.</span>
      </footer>
    </div>
  );
}
