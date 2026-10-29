// Typed client for the local FaceProof API. Every shape below mirrors what
// src/web/app.py returns; nothing is mocked or defaulted here.

export interface Health {
  version: string;
  demo_mode: boolean;
  chain_writes_enabled: boolean;
  models_present: boolean;
  search_provider: string;
  search_configured: boolean;
  chain: { name: string; chain_id: number; contract_configured: boolean; signer_configured: boolean };
  thresholds: { face_cosine: number; phash_max_distance: number };
  limits: { upload_bytes: number; record_bytes: number };
}

export interface DisclosureItem {
  service: string;
  what_is_sent: string;
  flag: string;
}
export interface Disclosure {
  provider: string;
  external: boolean;
  publish_provider?: string;
  items: DisclosureItem[];
}

export interface CandidateRow {
  page_url: string;
  image_url: string;
  domain: string;
  provider_position: number;
  is_social: boolean;
  status: string;
  evidence_type: string;
  face_similarity: string;
  phash_distance: number;
  faces_in_candidate: number;
  face_check_passed: boolean;
  derivative_check_passed: boolean;
  candidate_image_sha256: string;
  error?: string;
}

export interface VerificationRecord {
  schema: string;
  payload: {
    evidence_type?: string;
    created_at: string;
    test_mode?: { stub_engine: boolean; offline_fixture_provider: boolean };
    match: {
      matched_url: string;
      decision_rule: string;
      claim: string;
      limitations?: string[];
      face_similarity: string;
      face_cosine_threshold: string;
      phash_distance: number;
      phash_max_distance: number;
    };
    face: { engine: string };
  };
  integrity: { algorithm: string; verification_hash: string };
  anchor: { simulated?: boolean; tx_hash?: string; block_number?: number; explorer_url?: string; network?: string } | null;
}

export interface Manifest {
  file_count: number;
  files: { file: string; bytes: number; sha256: string }[];
}

export type JobState = "queued" | "running" | "succeeded" | "no_match" | "failed" | "cancelling" | "cancelled";

export interface JobStatus {
  id: string;
  status: JobState;
  stages: string[];
  current_stage: string;
  log: string[];
  exit_code: number | null;
  message: string;
  simulated_chain: boolean;
  demo_mode: boolean;
  record: VerificationRecord | null;
  candidates: CandidateRow[];
  artefacts: string[];
  manifest: Manifest | null;
}

export type CheckState = "pass" | "fail" | "error" | "skipped";
export interface VerifyReport {
  verdict: string;
  exit_code: number;
  message?: string;
  simulated: boolean;
  test_only: boolean;
  evidence_type?: string;
  record_hash?: string;
  checks: Record<string, { status: CheckState; detail: string }>;
  chain?: { network?: string; chain_id?: number; contract_address?: string; block_number?: number; block_timestamp?: number; tx_hash?: string; explorer_url?: string; submitter?: string };
  warnings?: string[];
  log: string[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let detail = `request failed (${res.status})`;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* keep the generic message */
  }
  throw new ApiError(res.status, detail);
}

export const api = {
  health: () => fetch("/api/health").then(parse<Health>),
  disclosure: (provider: string) => fetch(`/api/disclosure?provider=${encodeURIComponent(provider)}`).then(parse<Disclosure>),
  createJob: (form: FormData) => fetch("/api/jobs", { method: "POST", body: form }).then(parse<{ id: string; status: JobState }>),
  job: (id: string) => fetch(`/api/jobs/${id}`).then(parse<JobStatus>),
  deleteJob: (id: string) => fetch(`/api/jobs/${id}`, { method: "DELETE" }).then(parse<{ status: JobState }>),
  verify: (form: FormData) => fetch("/api/verify", { method: "POST", body: form }).then(parse<VerifyReport>),
  fileUrl: (id: string, name: string) => `/api/jobs/${id}/files/${name}`,
  demoSample: () => fetch("/api/demo/sample.png").then((r) => (r.ok ? r.blob() : Promise.reject(new ApiError(r.status, "demo sample unavailable")))),
};
