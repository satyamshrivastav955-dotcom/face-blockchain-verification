import { useEffect, useRef, useState, type ReactNode } from "react";

export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Rubber-stamp label. Tone is semantic (ok/err/warn/mute); the text always says what it means. */
export function Stamp({ tone, children, tilt = -4, big, delay = 0 }: { tone: "ok" | "err" | "warn" | "mute"; children: ReactNode; tilt?: number; big?: boolean; delay?: number }) {
  return (
    <span className={`stamp ${tone}${big ? " big" : ""}`} style={{ ["--tilt" as string]: `${tilt}deg`, animationDelay: `${delay}ms` }}>
      {children}
    </span>
  );
}

/** Fades/slides children in once when scrolled into view. */
export function Reveal({ children, className = "", delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    if (reducedMotion() || !("IntersectionObserver" in window)) return setSeen(true);
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true);
          io.disconnect();
        }
      },
      { threshold: 0.15 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} className={`reveal${seen ? " in" : ""} ${className}`} style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </div>
  );
}

/** Counts up to a real value (decimals preserved). Shows the final value immediately under reduced motion. */
export function CountUp({ value, decimals = 0, ms = 900 }: { value: number; decimals?: number; ms?: number }) {
  const [shown, setShown] = useState(reducedMotion() ? value : 0);
  useEffect(() => {
    if (reducedMotion()) return setShown(value);
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / ms);
      setShown(value * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    // rAF is paused in background tabs; always land on the real value.
    const done = window.setTimeout(() => setShown(value), ms + 150);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(done);
    };
  }, [value, ms]);
  return <>{shown.toFixed(decimals)}</>;
}

/** A ledger line: label ........ value */
export function Leader({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="leader">
      <span className="lk">{k}</span>
      <i aria-hidden="true" />
      <span className="lv">{v}</span>
    </div>
  );
}

/** Hidden SVG filter that roughens stamp edges like uneven ink. */
export function InkFilters() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true" focusable="false">
      <filter id="rough" x="-5%" y="-5%" width="110%" height="110%">
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="7" result="n" />
        <feDisplacementMap in="SourceGraphic" in2="n" scale="1.6" />
      </filter>
    </svg>
  );
}

/** Circular seal; rendered only when a record really exists. */
export function Seal({ label = "SHA-256 SEALED" }: { label?: string }) {
  return (
    <svg className="seal" viewBox="0 0 120 120" role="img" aria-label={label}>
      <defs>
        <path id="arc" d="M60,60 m-44,0 a44,44 0 1,1 88,0 a44,44 0 1,1 -88,0" />
      </defs>
      <circle cx="60" cy="60" r="56" fill="none" stroke="currentColor" strokeWidth="2.4" />
      <circle cx="60" cy="60" r="50" fill="none" stroke="currentColor" strokeWidth="0.8" strokeDasharray="2 3" />
      <text fontSize="9.5" letterSpacing="3.2" fill="currentColor" fontFamily="ui-monospace, Consolas, monospace" fontWeight="700">
        <textPath href="#arc" startOffset="0">{label} · {label} · </textPath>
      </text>
      <path d="M40 62 l14 14 28 -32" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
