"""
FastAPI backend for the local FaceProof web app.

A thin HTTP layer over the existing pipeline: registration and verification are
performed by ``run_register`` / ``run_verify`` - nothing is re-implemented here.

Local-first and defensive by default
------------------------------------
* bound to loopback by ``python -m src.web`` (``--host`` must be changed
  explicitly, and the app warns when it is);
* ``Host`` and ``Origin`` headers are checked, which blocks DNS-rebinding and
  cross-site requests to a service that only ever expects the local frontend;
* uploads are size-limited and validated as real, bounded images before use;
* no endpoint fetches a URL on the client's behalf; a client-supplied
  ``image_url`` is only forwarded to the search provider, after explicit consent;
* writing to a real blockchain needs the server flag ``--allow-chain-writes``;
  without it every registration uses the clearly labelled simulated chain;
* the stub engine / offline fixture are available only in ``--demo`` mode, which
  the UI labels on every screen;
* errors are returned as short messages, never stack traces; secrets are never
  returned (``/api/health`` reports only booleans).
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .. import __version__
from ..config import PROJECT_ROOT, ConfigError, Settings, load_settings
from ..evidence.record import MAX_RECORD_BYTES, RecordError
from ..pipeline import run_verify
from ..privacy import disclosure_for
from ..search import PROVIDERS, SearchError, build_provider
from ..ui import Console
from ..vision.face_detector import DET_MODEL_FILE, REC_MODEL_FILE
from ..vision.preprocess import ImageError, decode_image_safely
from .jobs import ARTEFACTS, JobLimitError, JobManager

__all__ = ["create_app", "MAX_UPLOAD_BYTES"]

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
DIST_DIR = PROJECT_ROOT / "web" / "dist"
DEMO_DIR = PROJECT_ROOT / "tests" / "data"


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Host or Origin is not the local app."""

    def __init__(self, app, allowed_hosts: set[str]) -> None:
        super().__init__(app)
        self.allowed_hosts = allowed_hosts

    async def dispatch(self, request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in self.allowed_hosts:
            return JSONResponse({"detail": "unexpected Host header"}, status_code=400)
        origin = request.headers.get("origin")
        if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
            origin_host = re.sub(r"^https?://", "", origin).rsplit(":", 1)[0].strip("[]").lower()
            if origin_host not in self.allowed_hosts:
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


async def _read_limited(upload: UploadFile, limit: int, what: str) -> bytes:
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{what} is larger than {limit // (1024 * 1024)} MiB")
    if not data:
        raise HTTPException(422, f"{what} is empty")
    return data


def create_app(
    settings: Settings | None = None,
    *,
    demo: bool = False,
    allow_chain_writes: bool = False,
    allowed_hosts: set[str] | None = None,
) -> FastAPI:
    base = settings or load_settings()
    base.validate()
    manager = JobManager(base, allow_offline_stub=demo, allow_chain_writes=allow_chain_writes)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        manager.shutdown()  # delete every job's temporary files

    app = FastAPI(
        title="FaceProof (local)",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        LocalOnlyMiddleware, allowed_hosts=allowed_hosts or {"127.0.0.1", "localhost", "::1", "testserver"}
    )
    app.state.manager = manager

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": f"internal error ({type(exc).__name__})"}, status_code=500)

    # -- status ------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        models_ok = all((base.models_dir / f).is_file() for f in (DET_MODEL_FILE, REC_MODEL_FILE))
        return {
            "version": __version__,
            "demo_mode": demo,
            "chain_writes_enabled": allow_chain_writes,
            "models_present": models_ok,
            "search_provider": base.search_provider,
            "search_configured": bool(base.serpapi_key or base.tineye_api_key),
            "chain": {
                "name": base.chain_name,
                "chain_id": base.chain_id,
                "contract_configured": bool(base.contract_address),
                "signer_configured": bool(base.private_key),
            },
            "thresholds": {
                "face_cosine": base.face_cosine_threshold,
                "phash_max_distance": base.phash_max_distance,
            },
            "limits": {"upload_bytes": MAX_UPLOAD_BYTES, "record_bytes": MAX_RECORD_BYTES},
        }

    @app.get("/api/disclosure")
    def disclosure(provider: str = "") -> dict[str, Any]:
        """What would leave this machine for a provider choice (read-only)."""
        name = provider or base.search_provider
        if name not in PROVIDERS:
            raise HTTPException(422, "unknown provider")
        if name == "local_fixture":
            return {"provider": name, "external": False, "items": []}
        try:
            built = build_provider(name, base)
            service, needs_url = built.name, built.needs_public_url
        except SearchError:
            # Not configured (no key): still disclose what would be sent.
            service, needs_url = name, name != "tineye"
        items = disclosure_for(
            service, needs_public_url=needs_url, publish_provider=base.publish_provider, have_image_url=False
        )
        return {
            "provider": name,
            "external": True,
            "publish_provider": base.publish_provider,
            "items": [{"service": i.service, "what_is_sent": i.what_is_sent, "flag": i.flag} for i in items],
        }

    # -- registration jobs ---------------------------------------------------

    @app.post("/api/jobs", status_code=202)
    async def create_job(
        image: UploadFile = File(...),
        provider: str = Form(""),
        simulate_chain: bool = Form(True),
        consent_external_search: bool = Form(False),
        consent_public_upload: bool = Form(False),
        require_face_match: bool = Form(False),
        minimal_evidence: bool = Form(False),
        image_url: str = Form(""),
        use_demo_engine: bool = Form(False),
    ) -> dict[str, Any]:
        data = await _read_limited(image, MAX_UPLOAD_BYTES, "image")
        try:
            decode_image_safely(data, label="uploaded image")
        except ImageError as exc:
            raise HTTPException(422, str(exc)) from exc

        name = (provider or base.search_provider).lower()
        if name not in PROVIDERS:
            raise HTTPException(422, "unknown provider")
        if name == "local_fixture" and not demo:
            raise HTTPException(403, "the offline fixture provider is only available in --demo mode")
        if use_demo_engine and not demo:
            raise HTTPException(403, "the stub engine is only available in --demo mode")
        if not simulate_chain and not allow_chain_writes:
            raise HTTPException(403, "real-chain registration is disabled; start the server with --allow-chain-writes")
        if len(image_url) > 2048:
            raise HTTPException(422, "image_url is too long")

        options = {
            "provider": name,
            "engine": "stub" if use_demo_engine else "opencv",
            "dry_run": simulate_chain,
            "allow_offline_stub": demo,
            "consent_external_search": consent_external_search,
            "consent_public_upload": consent_public_upload,
            "require_face_match": require_face_match,
            "minimal_evidence": minimal_evidence,
            "image_url": image_url.strip(),
            "fixture_path": str(DEMO_DIR / "candidates.json") if name == "local_fixture" else "",
        }
        try:
            job = manager.submit(data, options)
        except JobLimitError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {"id": job.id, "status": job.status}

    def _job(job_id: str):
        if not _JOB_ID.match(job_id):
            raise HTTPException(404, "no such job")
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "no such job")
        return job

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        job = _job(job_id)
        body: dict[str, Any] = {
            "id": job.id,
            "status": job.status,
            "stages": job.stages,
            "current_stage": job.current_stage,
            "log": job.log,
            "exit_code": job.exit_code,
            "message": job.message,
            "simulated_chain": bool(job.options.get("dry_run")),
            "demo_mode": demo,
        }
        body.update(manager.result(job))
        return body

    @app.get("/api/jobs/{job_id}/files/{name}")
    def job_file(job_id: str, name: str) -> FileResponse:
        job = _job(job_id)
        path = manager.artefact_path(job, name)
        if path is None:
            raise HTTPException(404, "no such artefact")
        return FileResponse(path, media_type=ARTEFACTS[name], filename=name if name.endswith(".json") else None)

    @app.delete("/api/jobs/{job_id}")
    def job_delete(job_id: str) -> dict[str, str]:
        if not _JOB_ID.match(job_id):
            raise HTTPException(404, "no such job")
        job = manager.cancel(job_id)
        if job is None:
            raise HTTPException(404, "no such job")
        return {"status": job.status}

    # -- verification --------------------------------------------------------

    @app.post("/api/verify")
    async def verify(
        record: UploadFile = File(...),
        image: UploadFile | None = File(None),
        simulated: bool = Form(False),
        job_id: str = Form(""),
    ) -> dict[str, Any]:
        record_bytes = await _read_limited(record, MAX_RECORD_BYTES, "record")
        image_bytes = await _read_limited(image, MAX_UPLOAD_BYTES, "image") if image and image.filename else None
        settings = base
        if job_id:
            settings = manager.settings_for(_job(job_id))

        def work() -> tuple[int, dict[str, Any], list[str]]:
            lines: list[str] = []

            class Capture(Console):
                def out(self, text: str = "") -> None:
                    if len(lines) < 400:
                        lines.append(text)

            with tempfile.TemporaryDirectory(prefix="faceproof-verify-") as tmp:
                rec = Path(tmp) / "record.json"
                rec.write_bytes(record_bytes)
                img_path = None
                if image_bytes is not None:
                    img_path = Path(tmp) / "image.img"
                    img_path.write_bytes(image_bytes)
                report: dict[str, Any] = {}
                code = run_verify(
                    settings,
                    rec,
                    dry_run=simulated,
                    image_path=img_path,
                    console=Capture(force_ascii=True),
                    report=report,
                )
            return code, report, lines

        loop = asyncio.get_running_loop()
        try:
            code, report, lines = await asyncio.wait_for(loop.run_in_executor(None, work), timeout=120)
        except RecordError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ConfigError as exc:
            raise HTTPException(400, f"configuration error: {exc}") from exc
        except FileNotFoundError as exc:  # pragma: no cover - defensive
            raise HTTPException(422, "record could not be read") from exc
        except asyncio.TimeoutError as exc:
            raise HTTPException(504, "verification timed out; the chain check may be unreachable") from exc
        report["exit_code"] = code
        report["log"] = lines
        return json.loads(json.dumps(report, default=str))

    @app.get("/api/demo/sample.png")
    def demo_sample() -> FileResponse:
        if not demo:
            raise HTTPException(404, "demo mode is off")
        return FileResponse(DEMO_DIR / "query.png", media_type="image/png")

    # -- static frontend (if built) -------------------------------------------

    if DIST_DIR.is_dir():
        app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="ui")
    else:

        @app.get("/")
        def no_frontend() -> JSONResponse:
            return JSONResponse(
                {
                    "detail": "frontend not built",
                    "hint": "cd web && npm install && npm run build, or use the CLI: python -m src.main --help",
                },
                status_code=200,
            )

    return app
