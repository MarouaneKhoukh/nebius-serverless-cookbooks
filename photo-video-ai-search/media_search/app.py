from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import base64
import binascii
import hmac
import secrets
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .config import Settings
from .embedding import Embedder, EmbeddingError
from .retrieval import rank_results
from .store import Store
from .generation import (BudgetExceeded, GenerationConflict, GenerationManager,
                         GenerationNotFound, GenerationSaveError, Ledger)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    kind: Literal["all", "image", "video"] = "all"
    limit: int = Field(default=12, ge=1, le=48)

    @field_validator("query")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Enter a description to search.")
        return value.strip()


class GenerationRequest(SearchRequest):
    prompt: str = Field(min_length=1, max_length=2000)
    approved: bool = Field(strict=True)
    request_id: uuid.UUID

    @field_validator("prompt")
    @classmethod
    def approved_prompt(cls, value):
        if not value.strip():
            raise ValueError("Review the image description before generating.")
        return value.strip()

    @field_validator("approved")
    @classmethod
    def explicit_approval(cls, value):
        if not value:
            raise ValueError("Approve the image description before generating.")
        return value


def create_app(settings=None, store=None, embedder=None, generator=None):
    settings = settings or Settings.from_env()
    settings.validate_demo()
    owned_store = store is None
    store = store or Store(settings)
    static = Path(__file__).parent / "static"
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    sessions = {}
    decisions = {}
    state_lock = threading.RLock()
    ledger = manager = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal ledger, manager
        store.ensure()
        ledger = Ledger(settings.data_dir)
        if settings.generation_url:
            manager = GenerationManager(settings, store, ledger, generator, embedder)
        try:
            yield
        finally:
            stopped = manager.close() if manager else True
            if ledger is not None and stopped:
                ledger.close()
            if owned_store and stopped:
                store.close()

    app = FastAPI(title="Photo + Video AI Search", lifespan=lifespan)

    @app.middleware("http")
    async def demo_boundary(request, call_next):
        if settings.demo_password:
            supplied = request.headers.get("authorization", "")
            try:
                scheme, value = supplied.split(" ", 1)
                raw = base64.b64decode(value, validate=True).decode()
                username, password = raw.split(":", 1)
                valid = (scheme.lower() == "basic"
                         and hmac.compare_digest(username.encode(), settings.demo_username.encode())
                         and hmac.compare_digest(password.encode(), settings.demo_password.encode()))
            except (ValueError, UnicodeError, binascii.Error):
                valid = False
            if not valid:
                return JSONResponse({"detail": "Sign in to this demo."}, status_code=401,
                                    headers={"WWW-Authenticate": 'Basic realm="Nebius media demo", charset="UTF-8"'})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def session(request, required=True):
        id_ = request.cookies.get("media_session", "")
        with state_lock:
            entry = sessions.get(id_)
            if entry and entry[1] > time.monotonic():
                return id_, entry[0]
        if required:
            raise HTTPException(403, "Refresh the page before making another request.")
        return None

    def check_post(request):
        id_, token = session(request)
        if not hmac.compare_digest(token.encode(), request.headers.get("x-csrf-token", "").encode()):
            raise HTTPException(403, "Refresh the page and try again.")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Requests must come from this gallery.")
        return id_

    def client_id(request):
        # With public Compose, only Caddy can connect to the web container.
        # Uvicorn trusts its forwarded address; never trust a header here directly.
        return request.client.host if request.client else "unknown"

    @app.get("/api/session")
    def new_session(request: Request):
        existing = session(request, required=False)
        with state_lock:
            if existing:
                id_, token = existing
            else:
                now = time.monotonic()
                for key in list(sessions):
                    if sessions[key][1] < now:
                        del sessions[key]
                if len(sessions) >= 2048:
                    raise HTTPException(429, "The demo has too many visitors. Please try later.")
                id_, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                sessions[id_] = (token, now + 3600)
            response = JSONResponse({"csrf_token": token})
            response.set_cookie("media_session", id_, max_age=3600, httponly=True,
                                samesite="strict", secure=request.url.scheme == "https")
            return response

    @app.exception_handler(BudgetExceeded)
    async def exhausted(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=429, headers={"Retry-After": "60"})

    @app.exception_handler(GenerationConflict)
    async def generation_conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(GenerationNotFound)
    async def generation_not_found(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(GenerationSaveError)
    async def generation_save_failed(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/api/status")
    def status():
        return {"collection": settings.collection, "points": store.count(),
                "model": settings.model, "dimensions": settings.dimensions,
                "generation_enabled": bool(settings.generation_url),
                "generation_model": settings.generation_model,
                "match_threshold": settings.match_threshold}

    @app.get("/api/gallery")
    def gallery(limit: int = 24, kind: Literal["all", "image", "video"] = "all", offset: str | None = None):
        if offset is not None:
            try:
                offset = str(uuid.UUID(offset))
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid gallery page offset.") from None
        return store.browse(max(1, min(48, limit)), kind, offset)

    @app.post("/api/search")
    def search(body: SearchRequest, request: Request):
        owner = check_post(request) if settings.public_demo else None
        if owner is None:
            current = session(request, required=False)
            owner = current[0] if current else None
        ledger.charge("search", client_id(request), settings.search_requests_per_hour, 3600, (10, 60))
        client = embedder
        try:
            # Browsing persisted media does not depend on an active GPU Endpoint.
            client = client or Embedder(settings)
            vector = client.text(body.query)
            # Rerank a wider visual candidate pool using descriptive metadata.
            # Keep the raw cosine, rather than treating one cutoff as truth.
            result = rank_results(body.query, store.search(vector, body.kind, 64),
                                  semantic_threshold=settings.match_threshold, limit=body.limit)
            if owner:
                with state_lock:
                    now = time.monotonic()
                    for key in list(decisions):
                        if decisions[key][1] < now:
                            del decisions[key]
                    if len(decisions) >= 4096:
                        decisions.pop(next(iter(decisions)))
                    decisions[(owner, body.query, body.kind)] = (result["match_found"], now + 300)
            return {"query": body.query, **result,
                    "match_threshold": settings.match_threshold,
                    "generation_available": bool(settings.generation_url) and body.kind != "video"}
        except (EmbeddingError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        finally:
            if client is not None and embedder is None:
                client.close()

    @app.post("/api/generations", status_code=202)
    def generate(body: GenerationRequest, request: Request):
        owner = check_post(request)
        if manager is None:
            raise HTTPException(503, "Image generation is not configured on this gallery.")
        if body.kind == "video":
            raise HTTPException(422, "FLUX generates images. Search Images to create an image.")
        with state_lock:
            decision = decisions.get((owner, body.query, body.kind))
        if decision is None or decision[1] < time.monotonic():
            raise HTTPException(409, "Search for this description first, then review and approve an image prompt.")
        # A person may choose a new image even when search returned matches.
        return manager.submit(body.query, body.prompt, str(body.request_id), owner, client_id(request))

    def owned_job(job_id, request):
        owner, _ = session(request)
        try:
            job_id = str(uuid.UUID(job_id))
        except ValueError:
            raise HTTPException(404, "Generation job not found.") from None
        if ledger.get_job(job_id, owner) is None:
            raise HTTPException(404, "Generation job not found.")
        return job_id, owner

    @app.get("/api/generations/{job_id}")
    def generation_status(job_id: str, request: Request):
        job_id, owner = owned_job(job_id, request)
        return ledger.get_job(job_id, owner)

    @app.get("/api/generations/{job_id}/image")
    def generation_preview(job_id: str, request: Request):
        job_id, owner = owned_job(job_id, request)
        if manager is None:
            raise HTTPException(503, "Image generation is not configured on this gallery.")
        return FileResponse(manager.preview_path(job_id, owner), media_type="image/png")

    @app.post("/api/generations/{job_id}/save")
    def save_generation(job_id: str, request: Request):
        check_post(request)
        job_id, owner = owned_job(job_id, request)
        if manager is None:
            raise HTTPException(503, "Image generation is not configured on this gallery.")
        return manager.save(job_id, owner)

    @app.post("/api/generations/{job_id}/discard")
    def discard_generation(job_id: str, request: Request):
        check_post(request)
        job_id, owner = owned_job(job_id, request)
        if manager is None:
            raise HTTPException(503, "Image generation is not configured on this gallery.")
        return manager.discard(job_id, owner)

    app.mount("/static", StaticFiles(directory=static), name="static")
    # Only prepared derivatives are mounted; neither originals nor .env is served.
    media_root = settings.data_dir / "media"
    media_root.mkdir(exist_ok=True)
    app.mount("/media", StaticFiles(directory=media_root), name="media")
    return app
