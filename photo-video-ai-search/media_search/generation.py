"""Bounded image generation, durable budgets and generated-media provenance."""
import base64
import binascii
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import queue
import sqlite3
import shutil
import threading
import time
import uuid

import httpx
from PIL import Image

from .embedding import Embedder
from .media import prepare_file


class GenerationError(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class GenerationConflict(RuntimeError):
    pass


class GenerationNotFound(RuntimeError):
    pass


class GenerationSaveError(RuntimeError):
    pass


class Generator:
    def __init__(self, settings, client=None):
        settings.require_generation()
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(600, connect=15), follow_redirects=False)

    def close(self):
        self.client.close()

    def image(self, prompt):
        try:
            response = self.client.post(self.settings.generation_url + "/v1/images/generations",
                headers={"Authorization": "Bearer " + self.settings.generation_token},
                json={"model": self.settings.generation_model, "prompt": prompt, "n": 1,
                      "size": "1024x1024", "response_format": "b64_json"})
            response.raise_for_status()
            if len(response.content) > 12 * 1024 * 1024:
                raise GenerationError("The generated response exceeded the demo image limit.")
            items = response.json()["data"]
            if len(items) != 1:
                raise ValueError("Expected one image")
            # Do not download arbitrary URLs returned by an upstream service.
            raw = base64.b64decode(items[0]["b64_json"], validate=True)
            if len(raw) > 8 * 1024 * 1024:
                raise GenerationError("The generated image exceeded the 8 MiB limit.")
            with Image.open(io.BytesIO(raw)) as image:
                if image.width * image.height > 2048 * 2048 or min(image.size) < 2:
                    raise ValueError("Unexpected image dimensions")
                image.load()
            return raw
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                raise GenerationError("The model declined this request or its output. Try another description.") from None
            if exc.response.status_code == 429:
                raise GenerationError("The GPU is busy. Please wait for the current request, then try again.") from None
            raise GenerationError(f"Generation Endpoint returned HTTP {exc.response.status_code}; check its readiness and token.") from None
        except httpx.HTTPError:
            raise GenerationError("Generation Endpoint is unavailable or timed out; check its running state.") from None
        except (ValueError, KeyError, TypeError, binascii.Error, OSError):
            raise GenerationError("Generation Endpoint returned an invalid image response.") from None

    def wait_ready(self, seconds=1800):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                response = self.client.get(self.settings.generation_url + "/v1/models",
                    headers={"Authorization": "Bearer " + self.settings.generation_token}, timeout=15)
                if response.status_code in (401, 403):
                    raise GenerationError("Generation Endpoint rejected authentication.")
                if response.is_success and any(m.get("id") == self.settings.generation_model
                    for m in response.json().get("data", [])):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        raise GenerationError("Generation model was not ready within the bounded wait.")


class Ledger:
    """Request caps survive a web-container restart. One web worker is supported."""
    def __init__(self, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(data_dir / "demo.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS requests (kind TEXT, client TEXT, at REAL)")
        self.db.execute("CREATE INDEX IF NOT EXISTS request_window ON requests(kind, at)")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT, key TEXT, query TEXT, status TEXT, result TEXT, created REAL)")
        # Add review fields without rewriting previously saved gallery records.
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}
        for column in ("prompt", "request_id"):
            if column not in columns:
                self.db.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS generation_request ON jobs(owner,request_id) WHERE request_id IS NOT NULL")
        self.db.execute("UPDATE jobs SET status='ready' WHERE status='saving'")
        self.db.execute("UPDATE jobs SET status='failed', result=? WHERE status IN ('queued','running')",
                        (json.dumps({"error": "The web server restarted before this job completed. Search again to retry."}),))
        self.db.commit()

    def charge(self, kind, client, global_limit, window, per_client=None):
        now = time.time()
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("DELETE FROM requests WHERE at < ?", (now - 86400,))
                since = now - window
                count = self.db.execute("SELECT COUNT(*) FROM requests WHERE kind=? AND at>=?", (kind, since)).fetchone()[0]
                if count >= global_limit:
                    raise BudgetExceeded("This demo's request budget is used up. Please try later.")
                if per_client:
                    limit, span = per_client
                    used = self.db.execute("SELECT COUNT(*) FROM requests WHERE kind=? AND client=? AND at>=?",
                                           (kind, client, now - span)).fetchone()[0]
                    if used >= limit:
                        raise BudgetExceeded("Please wait before making another request.")
                self.db.execute("INSERT INTO requests VALUES (?,?,?)", (kind, client, now))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def get_job(self, id_, owner):
        with self.lock:
            row = self.db.execute("SELECT status,result,prompt,query FROM jobs WHERE id=? AND owner=?", (id_, owner)).fetchone()
        if row is None:
            return None
        # Earlier editions saved automatically and used 'succeeded'. Their media
        # remain intact, while the review API describes them as already saved.
        status = "saved" if row[0] == "succeeded" else row[0]
        return {"id": id_, "status": status, "prompt": row[2] or row[3],
                **json.loads(row[1] or "{}")}

    def close(self):
        with self.lock:
            self.db.close()


class GenerationManager:
    def __init__(self, settings, store, ledger, generator=None, embedder=None):
        self.settings, self.store, self.ledger = settings, store, ledger
        self.generator, self.embedder = generator, embedder
        self.queue = queue.Queue(maxsize=4)
        self.review_lock = threading.RLock()
        self.private_root = settings.data_dir / ".generation-previews"
        self.private_root.mkdir(exist_ok=True)
        self.stopping = threading.Event()
        self.worker = threading.Thread(target=self._work, name="image-generation", daemon=True)
        self.worker.start()

    def submit(self, query, prompt, request_id, owner, client):
        # One browser approval has one request ID. Reusing that approval with
        # another prompt must never silently start or substitute an image.
        key = hashlib.sha256((self.settings.generation_model + "\n" + query + "\n" + prompt).encode()).hexdigest()
        with self.ledger.lock:
            existing = self.ledger.db.execute(
                "SELECT id,key FROM jobs WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
            if existing:
                if existing[1] != key:
                    raise GenerationConflict("This approval was already used with a different prompt. Review it again before generating.")
                return self.ledger.get_job(existing[0], owner)
            if self.queue.full():
                raise BudgetExceeded("The generation queue is full. Please try later.")
            self.ledger.charge("generation", client, self.settings.max_generations_per_day, 86400,
                (self.settings.generation_requests_per_hour_per_ip, 3600))
            id_ = str(uuid.uuid4())
            self.ledger.db.execute(
                "INSERT INTO jobs (id,owner,key,query,status,result,created,prompt,request_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (id_, owner, key, query, "queued", "{}", time.time(), prompt, request_id))
            self.ledger.db.commit()
            self.queue.put_nowait((id_, prompt))
        return {"id": id_, "status": "queued", "prompt": prompt}

    def _update(self, id_, status, **fields):
        with self.ledger.lock:
            self.ledger.db.execute("UPDATE jobs SET status=?, result=? WHERE id=?", (status, json.dumps(fields), id_))
            self.ledger.db.commit()

    def _job(self, id_, owner):
        job = self.ledger.get_job(id_, owner)
        if job is None:
            raise GenerationNotFound("Generation job not found.")
        return job

    def preview_path(self, id_, owner):
        job = self._job(id_, owner)
        path = self.private_root / id_ / "image.png"
        if job["status"] not in ("ready", "saving") or not path.is_file():
            raise GenerationNotFound("Image preview not found.")
        return path

    def save(self, id_, owner):
        # The single web worker serializes review actions so two clicks cannot
        # embed or index the same preview twice. Status reads stay responsive.
        with self.review_lock:
            job = self._job(id_, owner)
            if job["status"] == "saved":
                return job
            if job["status"] != "ready":
                raise GenerationConflict("Wait for the image preview before adding it to your collection.")
            source = self.preview_path(id_, owner)
            preview = job["preview"]
            self._update(id_, "saving", preview=preview)
            emb = None
            try:
                private = source.parent
                cache = private / "index.json"
                if cache.is_file():
                    prepared = json.loads(cache.read_text())
                else:
                    # Preparing and embedding still happen in the private area.
                    # Only this explicit Save action can publish the derivatives.
                    prepared_root = private / "prepared"
                    media = next(prepare_file(source, prepared_root))
                    emb = self.embedder or Embedder(self.settings)
                    vector = emb.media(prepared_root / media.media_path, "image")
                    payload = asdict(media)
                    payload.update(title=job["prompt"][:90], generated=True,
                        generation_model=self.settings.generation_model, prompt=job["prompt"],
                        generated_at=preview["generated_at"], source_name="AI-generated with FLUX 3 Image Klein")
                    payload["media_path"] = str(Path(media.media_path).relative_to("media"))
                    payload["thumbnail_path"] = str(Path(media.thumbnail_path).relative_to("media"))
                    prepared = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "media-search:" + media.id)),
                                "vector": vector, "payload": payload, "asset": media.id}
                    # A temporary indexing failure can retry without paying for
                    # another generation or repeating a successful embedding.
                    temporary = cache.with_suffix(".tmp")
                    temporary.write_text(json.dumps(prepared))
                    temporary.replace(cache)
                source_assets = private / "prepared" / "media" / prepared["asset"]
                destination = self.settings.data_dir / "media" / prepared["asset"]
                if not destination.exists():
                    staging = destination.with_name(".save-" + id_)
                    shutil.copytree(source_assets, staging, dirs_exist_ok=True)
                    try:
                        staging.rename(destination)
                    except OSError:
                        if not destination.is_dir():
                            raise
                    finally:
                        if staging.exists():
                            shutil.rmtree(staging)
                # The deterministic point ID also makes an ambiguous database
                # response safe to retry without adding a duplicate library item.
                self.store.upsert(prepared["id"], prepared["vector"], prepared["payload"])
                from types import SimpleNamespace
                item = self.store.item(SimpleNamespace(id=prepared["id"], payload=prepared["payload"], score=None))
                self._update(id_, "saved", item=item)
            except Exception:
                self._update(id_, "ready", preview=preview,
                    error="Could not add this image to your collection. Your preview is kept; try Save again.")
                raise GenerationSaveError("Could not add this image to your collection. Your preview is kept; try Save again.") from None
            finally:
                if emb is not None and self.embedder is None:
                    emb.close()
            shutil.rmtree(source.parent, ignore_errors=True)
            return self.ledger.get_job(id_, owner)

    def discard(self, id_, owner):
        with self.review_lock:
            job = self._job(id_, owner)
            if job["status"] == "saved":
                raise GenerationConflict("This image is already in your collection. Discard only removes an unsaved preview.")
            if job["status"] == "discarded":
                return job
            if job["status"] != "ready":
                raise GenerationConflict("Wait for the image preview before discarding it.")
            shutil.rmtree(self.private_root / id_, ignore_errors=True)
            self._update(id_, "discarded")
            return self.ledger.get_job(id_, owner)

    def _work(self):
        while not self.stopping.is_set():
            try:
                id_, prompt = self.queue.get(timeout=0.25)
            except queue.Empty:
                continue
            gen = None
            try:
                self._update(id_, "running")
                gen = self.generator or Generator(self.settings)
                image = gen.image(prompt)
                private = self.private_root / id_
                private.mkdir(exist_ok=True)
                # Re-encode validated pixels and never expose unapproved output
                # through the gallery's public /media static mount.
                with Image.open(io.BytesIO(image)) as decoded:
                    decoded.convert("RGB").save(private / "image.png", "PNG")
                preview = {"kind": "image", "title": prompt[:90], "prompt": prompt,
                           "generated": True, "generation_model": self.settings.generation_model,
                           "generated_at": time.time(), "media_url": f"/api/generations/{id_}/image",
                           "thumbnail_url": f"/api/generations/{id_}/image"}
                self._update(id_, "ready", preview=preview)
            except Exception as exc:
                # SDK exceptions may contain credentials, prompts or image data.
                message = str(exc) if type(exc) is GenerationError else (
                    "Image generation failed. Check the generation service, then review your prompt to retry.")
                shutil.rmtree(self.private_root / id_, ignore_errors=True)
                self._update(id_, "failed", error=message)
            finally:
                if gen is not None and self.generator is None:
                    gen.close()
                self.queue.task_done()

    def close(self):
        self.stopping.set()
        self.worker.join(timeout=1)
        # Running HTTP inference can still be finishing. Its thread is daemonized;
        # retain the ledger until it exits instead of closing it underneath a job.
        return not self.worker.is_alive()
