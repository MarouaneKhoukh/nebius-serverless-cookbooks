from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .config import Settings
from .embedding import Embedder, EmbeddingError
from .store import Store


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


def create_app(settings=None, store=None, embedder=None):
    settings = settings or Settings.from_env()
    owned_store = store is None
    store = store or Store(settings)
    static = Path(__file__).parent / "static"
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        store.ensure()
        try:
            yield
        finally:
            if owned_store:
                store.close()

    app = FastAPI(title="Photo + Video AI Search", lifespan=lifespan)

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/api/status")
    def status():
        return {"collection": settings.collection, "points": store.count(),
                "model": settings.model, "dimensions": settings.dimensions}

    @app.get("/api/gallery")
    def gallery(limit: int = 24, kind: Literal["all", "image", "video"] = "all", offset: str | None = None):
        if offset is not None:
            try:
                offset = str(uuid.UUID(offset))
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid gallery page offset.") from None
        return store.browse(max(1, min(48, limit)), kind, offset)

    @app.post("/api/search")
    def search(body: SearchRequest):
        client = embedder
        try:
            # Browsing persisted media does not depend on an active GPU Endpoint.
            client = client or Embedder(settings)
            vector = client.text(body.query)
            return {"query": body.query, "items": store.search(vector, body.kind, body.limit)}
        except (EmbeddingError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        finally:
            if client is not None and embedder is None:
                client.close()

    app.mount("/static", StaticFiles(directory=static), name="static")
    # Only prepared derivatives are mounted; neither originals nor .env is served.
    media_root = settings.data_dir / "media"
    media_root.mkdir(exist_ok=True)
    app.mount("/media", StaticFiles(directory=media_root), name="media")
    return app
