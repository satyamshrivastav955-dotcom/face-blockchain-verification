"""
In-process job manager for the local FaceProof web app.

Each registration runs the *existing* pipeline (``run_register``) in a worker
thread against a private temporary directory. Nothing is simulated here: the
job's status, stage list, log lines, candidates and record are whatever the
pipeline actually produced.

Safety properties
-----------------
* one worker and a short queue, so a burst of uploads cannot exhaust memory;
* every job directory is created with ``tempfile.mkdtemp`` and deleted on
  request, on expiry (``JOB_TTL_SECONDS``) and at shutdown;
* the browser only ever supplies a job id (validated as hex), never a path;
* only whitelisted artefact names can be read back.

Cancellation is cooperative and honest: a queued job is dropped; a running job
cannot be interrupted inside the pipeline, so it is marked ``cancelling`` and its
result and files are discarded when it finishes.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Settings
from ..pipeline import EXIT_ERROR, EXIT_NO_MATCH, EXIT_OK, run_register
from ..ui import Console

__all__ = ["Job", "JobManager", "JobLimitError", "ARTEFACTS", "JOB_TTL_SECONDS"]

JOB_TTL_SECONDS = 3600
MAX_QUEUED = 4
MAX_LOG_LINES = 400

# Files a client may read from a finished job, and nothing else.
ARTEFACTS = {
    "comparison.png": "image/png",
    "query_face.png": "image/png",
    "matched_face.png": "image/png",
    "candidates.json": "application/json",
    "manifest.json": "application/json",
    "verification.json": "application/json",
    "anchor.json": "application/json",
}


class JobLimitError(RuntimeError):
    """Too many jobs are already queued."""


class RecordingConsole(Console):
    """Console that records what the pipeline prints instead of printing it."""

    def __init__(self, job: Job) -> None:
        super().__init__(force_ascii=True)
        self.job = job

    def out(self, text: str = "") -> None:
        if len(self.job.log) < MAX_LOG_LINES:
            self.job.log.append(text)

    def step(self, text: str) -> None:
        self.job.stages.append(text)
        self.job.current_stage = text
        super().step(text)


@dataclass
class Job:
    id: str
    dir: Path
    options: dict[str, Any]
    status: str = "queued"  # queued running succeeded no_match failed cancelling cancelled
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    stages: list[str] = field(default_factory=list)
    current_stage: str = ""
    log: list[str] = field(default_factory=list)
    exit_code: int | None = None
    message: str = ""
    cancel_requested: bool = False


class JobManager:
    def __init__(self, base_settings: Settings, *, allow_offline_stub: bool, allow_chain_writes: bool) -> None:
        self.base = base_settings
        self.allow_offline_stub = allow_offline_stub
        self.allow_chain_writes = allow_chain_writes
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._closed = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="faceproof-job")

    # -- lifecycle ---------------------------------------------------------

    def submit(self, image_bytes: bytes, options: dict[str, Any]) -> Job:
        self.reap()
        with self._lock:
            waiting = sum(1 for j in self._jobs.values() if j.status in ("queued", "running"))
            if waiting >= MAX_QUEUED + 1:
                raise JobLimitError("too many jobs in progress; wait for one to finish")
            job_id = uuid.uuid4().hex
            directory = Path(tempfile.mkdtemp(prefix="faceproof-"))
            job = Job(id=job_id, dir=directory, options=options)
            self._jobs[job_id] = job
        (directory / "upload.img").write_bytes(image_bytes)
        self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        self.reap()
        return self._jobs.get(job_id)

    def settings_for(self, job: Job) -> Settings:
        return dataclasses.replace(
            self.base,
            root=job.dir,
            models_path=self.base.models_dir,
            fixture_path=str(job.options.get("fixture_path") or ""),
        )

    def cancel(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status == "queued":
                job.status = "cancelled"
                job.cancel_requested = True
                self._discard(job)
            elif job.status == "running":
                job.status = "cancelling"
                job.cancel_requested = True
            else:
                self._discard(job)
                self._jobs.pop(job_id, None)
        return job

    def reap(self) -> None:
        now = time.time()
        with self._lock:
            for job_id, job in list(self._jobs.items()):
                if job.finished_at and now - job.finished_at > JOB_TTL_SECONDS:
                    self._discard(job)
                    self._jobs.pop(job_id, None)

    def shutdown(self) -> None:
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            for job in self._jobs.values():
                self._discard(job)
            self._jobs.clear()

    @staticmethod
    def _discard(job: Job) -> None:
        shutil.rmtree(job.dir, ignore_errors=True)

    # -- execution ---------------------------------------------------------

    def _run(self, job: Job) -> None:
        with self._lock:
            if job.cancel_requested or self._closed:
                return
            job.status = "running"
        settings = self.settings_for(job)
        opts = job.options
        try:
            code = run_register(
                settings,
                job.dir / "upload.img",
                provider_name=opts["provider"],
                engine_name=opts["engine"],
                image_url=opts.get("image_url", ""),
                dry_run=bool(opts["dry_run"]),
                allow_offline_stub=bool(opts.get("allow_offline_stub")),
                consent_external_search=bool(opts.get("consent_external_search")),
                consent_public_upload=bool(opts.get("consent_public_upload")),
                require_face_match=bool(opts.get("require_face_match")),
                minimal_evidence=bool(opts.get("minimal_evidence")),
                console=RecordingConsole(job),
            )
            status = {EXIT_OK: "succeeded", EXIT_NO_MATCH: "no_match"}.get(code, "failed")
            message = self._message_for(job, code)
        except Exception as exc:  # noqa: BLE001 - never leak a traceback to the browser
            code, status = EXIT_ERROR, "failed"
            message = f"{type(exc).__name__}: {str(exc)[:240]}"
        with self._lock:
            job.exit_code = code
            job.message = message
            job.finished_at = time.time()
            if job.cancel_requested or self._closed:
                # Cancelled, or the server stopped while this ran: leave no files behind.
                job.status = "cancelled"
                self._discard(job)
            else:
                job.status = status
            job.current_stage = ""

    @staticmethod
    def _message_for(job: Job, code: int) -> str:
        if code == EXIT_OK:
            return "Registered. See the record and evidence below."
        if code == EXIT_NO_MATCH:
            return "No candidate passed independent confirmation. Nothing was registered."
        # The pipeline prints its failure reason as a ' [X] ...' / 'X ...' line.
        for line in reversed(job.log):
            if "[X]" in line:
                return line.replace("[X]", "").strip()[:300]
        return "The run could not be completed. See the log."

    # -- results -----------------------------------------------------------

    def result(self, job: Job) -> dict[str, Any]:
        """Real artefacts from a finished job (empty fields if not produced)."""
        out: dict[str, Any] = {"record": None, "candidates": [], "artefacts": [], "manifest": None}
        if job.status not in ("succeeded", "no_match", "failed"):
            return out
        settings = self.settings_for(job)
        record_path = settings.output_dir / "verification.json"
        if record_path.is_file():
            out["record"] = json.loads(record_path.read_text(encoding="utf-8"))
        run_dirs = (
            sorted(p for p in settings.evidence_dir.glob("*") if p.is_dir()) if settings.evidence_dir.is_dir() else []
        )
        if run_dirs:
            run = run_dirs[-1]
            cand = run / "candidates.json"
            if cand.is_file():
                out["candidates"] = json.loads(cand.read_text(encoding="utf-8"))
            man = run / "manifest.json"
            if man.is_file():
                out["manifest"] = json.loads(man.read_text(encoding="utf-8"))
            out["artefacts"] = [n for n in ARTEFACTS if (run / n).is_file()]
        if record_path.is_file() and "verification.json" not in out["artefacts"]:
            out["artefacts"].append("verification.json")
        return out

    def artefact_path(self, job: Job, name: str) -> Path | None:
        if name not in ARTEFACTS:
            return None
        settings = self.settings_for(job)
        if name == "verification.json":
            path = settings.output_dir / name
            return path if path.is_file() else None
        for run in sorted(settings.evidence_dir.glob("*")) if settings.evidence_dir.is_dir() else []:
            path = run / name
            if path.is_file() and not path.is_symlink():
                return path
        return None
