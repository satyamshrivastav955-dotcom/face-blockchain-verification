import { explorerFetcher, verifyRecord, type Report } from "./core";

const EXPLORERS = ["https://blockstream.info/api", "https://mempool.space/api"];
const MAX_RECORD = 5 * 1024 * 1024;
const MAX_IMAGE = 200 * 1024 * 1024;

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const recordInput = $<HTMLInputElement>("record-file");
const imageInput = $<HTMLInputElement>("image-file");
const runBtn = $<HTMLButtonElement>("run");
const clearBtn = $<HTMLButtonElement>("clear");
const pin = $<HTMLInputElement>("pin");
const resultEl = $("result");
const netlog = $("netlog");

let recordText: string | null = null;
let imageBytes: Uint8Array | null = null;

// Every network request this page makes is shown to the user. The wrapper logs and delegates;
// the CSP is what actually forbids anything else.
const loggedFetch: typeof fetch = async (input, init) => {
  const url = String(input instanceof Request ? input.url : input);
  const none = netlog.querySelector(".none");
  if (none) none.remove();
  const li = document.createElement("li");
  li.textContent = `GET ${url}`;
  netlog.appendChild(li);
  return fetch(input, { ...init, method: "GET", credentials: "omit", referrerPolicy: "no-referrer" });
};

function setName(id: string, text: string, box: string, has: boolean) {
  $(id).textContent = text;
  $(box).classList.toggle("has", has);
}

async function loadRecord(file: File | undefined) {
  recordText = null;
  if (!file) return refresh();
  if (file.size > MAX_RECORD) {
    setName("record-name", "Too large to be a record (limit 5 MiB).", "drop-record", false);
    return refresh();
  }
  recordText = await file.text();
  setName("record-name", `${file.name} (${file.size.toLocaleString()} bytes)`, "drop-record", true);
  refresh();
}

async function loadImage(file: File | undefined) {
  imageBytes = null;
  if (!file) return refresh();
  if (file.size > MAX_IMAGE) {
    setName("image-name", "That file is too large for in-browser hashing (limit 200 MiB).", "drop-image", false);
    return refresh();
  }
  imageBytes = new Uint8Array(await file.arrayBuffer());
  setName("image-name", `${file.name} (${file.size.toLocaleString()} bytes)`, "drop-image", true);
  refresh();
}

function refresh() {
  runBtn.disabled = recordText === null;
  if (recordText !== null) void run();
}

const LABELS: Record<string, string> = {
  local_integrity: "Hash",
  signature: "Signature",
  image_binding: "Image",
  anchor: "Timestamp",
};
const VERDICT_TEXT: Record<Report["verdict"], [string, string]> = {
  verified: ["Verified", "Every check that could run passed."],
  failed: ["Failed", "At least one check failed. Do not rely on this record for this file."],
  inconclusive: ["Inconclusive", "A required check could not run. Nothing is claimed either way."],
  not_anchored: ["Not anchored", "The record is intact, but there is no confirmed time evidence for it."],
};

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function render(report: Report, hasImage: boolean) {
  resultEl.hidden = false;
  resultEl.replaceChildren();
  const [word, sentence] = VERDICT_TEXT[report.verdict];
  const verdict = el("div", "verdict");
  verdict.append(el("span", `stamp ${report.verdict}`, word), el("p", undefined, sentence));
  resultEl.append(verdict);

  const list = el("ul", "checks");
  for (const [key, label] of Object.entries(LABELS)) {
    const c = report.checks[key];
    if (!c) continue;
    const li = el("li");
    li.append(el("span", "name", label));
    const why = el("span", "why");
    why.append(el("span", `badge ${c.status}`, c.status === "skipped" ? "not run" : c.status), document.createTextNode(c.detail || "-"));
    li.append(why);
    list.append(li);
  }
  resultEl.append(list);

  const keys = Object.keys(report.facts);
  if (keys.length) {
    const dl = el("dl", "facts");
    for (const k of keys) dl.append(el("dt", undefined, k.replace(/_/g, " ")), el("dd", undefined, report.facts[k]));
    resultEl.append(dl);
  }
  if (!hasImage) {
    resultEl.append(el("p", "note", "No image was provided, so this only shows the record is unchanged. Add the file to check it is the one described."));
  }
  if (report.verdict === "verified") {
    resultEl.append(el("p", "note", "Verified means the record is intact" + (hasImage ? " and describes exactly this file" : "") + ". It does not mean the image is genuine or that anyone depicted is who a caption says."));
  }
  resultEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function run() {
  if (recordText === null) return;
  let record: unknown;
  try {
    record = JSON.parse(recordText);
  } catch {
    render({ verdict: "failed", checks: { local_integrity: { status: "fail", detail: "that file is not valid JSON" } }, facts: {} }, false);
    return;
  }
  const trusted = pin.value.trim() ? [pin.value.trim()] : [];
  if (trusted.some((k) => !/^[0-9a-fA-F]{64}$/.test(k))) {
    render({ verdict: "failed", checks: { signature: { status: "fail", detail: "the pinned key must be 64 hex characters" } }, facts: {} }, false);
    return;
  }
  runBtn.disabled = true;
  runBtn.textContent = "Verifying...";
  try {
    const report = await verifyRecord(record, {
      image: imageBytes,
      trustedKeys: trusted,
      fetchHeader: explorerFetcher(EXPLORERS, loggedFetch),
    });
    render(report, imageBytes !== null);
  } finally {
    runBtn.textContent = "Verify";
    runBtn.disabled = recordText === null;
  }
}

function wireDrop(boxId: string, input: HTMLInputElement) {
  const box = $(boxId);
  for (const t of ["dragenter", "dragover"]) box.addEventListener(t, (e) => { e.preventDefault(); box.classList.add("over"); });
  for (const t of ["dragleave", "drop"]) box.addEventListener(t, () => box.classList.remove("over"));
  box.addEventListener("drop", (e) => {
    e.preventDefault();
    const f = (e as DragEvent).dataTransfer?.files?.[0];
    if (f) {
      const dt = new DataTransfer();
      dt.items.add(f);
      input.files = dt.files;
      input.dispatchEvent(new Event("change"));
    }
  });
}

recordInput.addEventListener("change", () => void loadRecord(recordInput.files?.[0]));
imageInput.addEventListener("change", () => void loadImage(imageInput.files?.[0]));
pin.addEventListener("change", () => recordText !== null && void run());
runBtn.addEventListener("click", () => void run());
clearBtn.addEventListener("click", () => {
  recordInput.value = "";
  imageInput.value = "";
  pin.value = "";
  recordText = null;
  imageBytes = null;
  setName("record-name", "Drop or choose a .json record", "drop-record", false);
  setName("image-name", "Drop or choose the exact file", "drop-image", false);
  resultEl.hidden = true;
  runBtn.disabled = true;
});
wireDrop("drop-record", recordInput);
wireDrop("drop-image", imageInput);

$("env").textContent = crypto?.subtle ? "WebCrypto available" : "WebCrypto unavailable: this page needs HTTPS or localhost";
