"""Thin owner-only HTTP adapter. Public publication serves web/ without this API.

Pass a high-entropy owner_token explicitly. Tokens stay in Authorization headers;
there are no auth cookies, URL tokens, CORS grants or default credentials. Mutation
clients must send an exact Origin matching the validated Host and ASGI scheme.
Run behind an authorized TLS endpoint whose proxy headers are trusted narrowly.
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from swe_workbench import __version__
from swe_workbench.assets import bundled_directory

MAX_BODY = 64 * 1024
WEB_DIR = bundled_directory("web")
HOST = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\])(?::[0-9]{1,5})?\Z")
CRITERIA = {"task_clarity", "evidence_adequacy", "requested_behavior", "preserved_behavior", "unsupported_claims"}


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Operation(Payload):
    operation_key: str = Field(min_length=1, max_length=160)


class Processing(Payload):
    workers: StrictInt = Field(default=1, ge=1, le=2)


class Review(Operation):
    expected_revision: StrictInt = Field(ge=0)
    evidence_digest: str = Field(min_length=1, max_length=128)
    rubric_digest: str = Field(min_length=1, max_length=128)
    decision: Literal["accepted", "rejected", "needs-work"]
    reason: str = Field(max_length=8000)
    criteria: dict[str, Literal["pass", "fail", "uncertain", "not-assessed"]]


def error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def create_app(root: Path | str, *, owner_token: str | None = None) -> FastAPI:
    # Import lazily so static assets and isolated adapter tests need no running core.
    from swe_workbench.core import Workbench
    from swe_workbench.errors import WorkbenchError

    if owner_token is not None and (len(owner_token) < 32 or not owner_token.isascii()):
        raise ValueError("owner_token must contain at least 32 ASCII characters")
    root = Path(root)
    workbench = Workbench(root)
    workbench.initialize()
    app = FastAPI(title="SWE Data Workbench", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.workbench = workbench

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        headers = request.headers
        host_values = [value for name, value in request.scope["headers"] if name.lower() == b"host"]
        host = headers.get("host", "")
        if len(host_values) != 1 or not HOST.fullmatch(host):
            response = error("invalid_host", "A valid single Host header is required.", 400)
        elif request.scope["path"].startswith("/api/"):
            path = request.scope["path"]
            if path != "/api/health":
                supplied = headers.get("authorization", "")
                if owner_token is None or not secrets.compare_digest(supplied.encode(), ("Bearer " + owner_token).encode()):
                    response = error("unauthorized", "Owner authorization is required.", 401)
                elif headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
                    response = error("origin_forbidden", "Use the same origin as this workbench.", 403)
                elif request.method not in {"GET", "HEAD"}:
                    expected = request.scope["scheme"] + "://" + host
                    origins = [value for name, value in request.scope["headers"] if name.lower() == b"origin"]
                    if len(origins) != 1 or headers.get("origin") != expected:
                        response = error("origin_forbidden", "An exact same-origin Origin header is required.", 403)
                    elif headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        response = error("invalid_content_type", "Use application/json.", 415)
                    else:
                        body = bytearray()
                        async for chunk in request.stream():
                            body.extend(chunk)
                            if len(body) > MAX_BODY:
                                break
                        if len(body) > MAX_BODY:
                            response = error("body_too_large", "Request exceeds 64 KiB.", 413)
                        else:
                            request._body = bytes(body)
                            response = await call_next(request)
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        return response

    @app.exception_handler(WorkbenchError)
    async def domain_error(request, exc):
        return error(exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error("invalid_request", "The request does not match the required schema.", 422)

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/batches")
    def batches():
        return workbench.list_batches()

    @app.get("/api/batches/{batch_id}")
    def batch(batch_id: str):
        return workbench.batch(batch_id)

    @app.get("/api/batches/{batch_id}/submissions")
    def submissions(batch_id: str):
        return workbench.submissions(batch_id)

    @app.get("/api/submissions/{submission_id}")
    def submission(submission_id: str):
        return workbench.submission(submission_id)

    @app.get("/api/batches/{batch_id}/audit")
    def audit(batch_id: str):
        return workbench.audit_events(batch_id)

    @app.post("/api/import-sample")
    def import_sample(body: Operation):
        return workbench.import_sample(operation_key=body.operation_key)

    @app.post("/api/batches/{batch_id}/process")
    def process(batch_id: str, body: Processing):
        # FastAPI runs synchronous endpoints in its thread pool; the core owns
        # process locking, child lifecycle and actual bounded worker scheduling.
        return workbench.process(batch_id, workers=body.workers)

    @app.post("/api/submissions/{submission_id}/review")
    def review(submission_id: str, body: Review):
        if set(body.criteria) != CRITERIA:
            return error("invalid_criteria", "Assess all five rubric criteria.", 422)
        return workbench.review(submission_id, **body.model_dump(), actor="operator")

    @app.post("/api/batches/{batch_id}/export")
    def export(batch_id: str, body: Operation):
        from swe_workbench.exporter import export_batch
        result = export_batch(workbench, batch_id, root / "exports", body.operation_key)
        return {key: value for key, value in result.items() if key not in {"path", "location"}}

    # Fixed allowlist: never expose the database, root, fixture workspaces or
    # arbitrary URL paths through a generic application-directory static mount.
    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/app.js")
    def javascript():
        return FileResponse(WEB_DIR / "app.js", media_type="text/javascript")

    @app.get("/style.css")
    def stylesheet():
        return FileResponse(WEB_DIR / "style.css", media_type="text/css")

    return app
