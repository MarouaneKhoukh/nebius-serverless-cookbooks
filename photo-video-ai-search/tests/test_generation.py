"""Offline fixtures verify reviewed generation and privacy, never model quality."""
import base64
from dataclasses import replace
import io
import json
import math
import sqlite3
import threading
import time
import uuid

from fastapi.testclient import TestClient
import httpx
from PIL import Image
import pytest
from qdrant_client import QdrantClient

from media_search.app import create_app
from media_search.config import Settings
from media_search.generation import BudgetExceeded, GenerationError, Generator, Ledger
from media_search.store import Store


def settings(tmp_path, **fields):
    return replace(Settings(data_dir=tmp_path / "data", dimensions=3,
        embedding_url="https://embedding.invalid", embedding_token="fixture-only",
        generation_url="https://generation.invalid", generation_token="fixture-only"), **fields)


def png():
    out = io.BytesIO()
    Image.new("RGB", (64, 64), "purple").save(out, "PNG")
    return out.getvalue()


class FakeEmbedder:
    def __init__(self):
        self.text_calls = self.media_calls = 0

    def text(self, value):
        self.text_calls += 1
        return [1., 0., 0.]

    def media(self, path, kind):
        assert path.is_file() and kind == "image"
        self.media_calls += 1
        return [1., 0., 0.]


class FakeGenerator:
    def __init__(self, hold=None):
        self.calls = []
        self.hold = hold

    def image(self, prompt):
        self.calls.append(prompt)
        if self.hold:
            assert self.hold.wait(5)
        return png()


def session(web):
    return {"X-CSRF-Token": web.get("/api/session").json()["csrf_token"]}


def approved(query="a purple castle", **changes):
    return {"query": query, "kind": "image", "prompt": query,
            "approved": True, "request_id": str(uuid.uuid4()), **changes}


def search(web, body, headers):
    return web.post("/api/search", json={"query": body["query"], "kind": body["kind"]}, headers=headers)


def completed(web, id_):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = web.get("/api/generations/" + id_).json()
        if result["status"] in ("ready", "saved", "discarded", "failed"):
            return result
        time.sleep(.02)
    pytest.fail("Offline generation job did not complete")


def test_search_never_generates_and_explicit_prompt_approval_is_required(tmp_path):
    s = settings(tmp_path, public_demo=True)
    store = Store(s, QdrantClient(":memory:"))
    emb, gen = FakeEmbedder(), FakeGenerator()
    with TestClient(create_app(s, store, emb, gen)) as web:
        headers, body = session(web), approved()
        assert search(web, body, headers).json()["items"] == []
        assert gen.calls == [] and store.count() == 0
        for missing in ("prompt", "approved", "request_id"):
            assert web.post("/api/generations", json={k: v for k, v in body.items() if k != missing}, headers=headers).status_code == 422
        for value in (False, "true", 1):
            assert web.post("/api/generations", json={**body, "approved": value}, headers=headers).status_code == 422
        assert gen.calls == [] and emb.media_calls == 0
    store.close()


def test_private_preview_is_only_added_after_save_and_save_is_idempotent(tmp_path):
    s = settings(tmp_path, public_demo=True)
    store = Store(s, QdrantClient(":memory:"))
    emb, gen = FakeEmbedder(), FakeGenerator()
    with TestClient(create_app(s, store, emb, gen)) as web:
        headers = session(web)
        body = approved(prompt="A purple castle with a wide green garden")
        found = search(web, body, headers).json()
        assert not found["match_found"] and found["generation_available"]
        first = web.post("/api/generations", json=body, headers=headers)
        assert first.status_code == 202
        id_ = first.json()["id"]
        assert web.post("/api/generations", json=body, headers=headers).json()["id"] == id_
        ready = completed(web, id_)
        assert ready["status"] == "ready" and ready["prompt"] == body["prompt"]
        assert "item" not in ready
        assert web.get(ready["preview"]["media_url"]).status_code == 200
        assert web.get(ready["preview"]["media_url"]).headers["cache-control"] == "no-store"
        assert store.count() == 0 and emb.media_calls == 0
        assert list((s.data_dir / "media").iterdir()) == []
        assert web.get("/api/gallery").json()["items"] == []
        saved = web.post(f"/api/generations/{id_}/save", headers=headers)
        assert saved.status_code == 200
        done = saved.json()
        assert done["status"] == "saved"
        item = done["item"]
        assert item["generated"] is True and item["prompt"] == body["prompt"]
        assert item["generation_model"] == s.generation_model
        assert web.get(item["media_url"]).status_code == 200
        assert web.get(item["thumbnail_url"]).status_code == 200
        assert web.get(ready["preview"]["media_url"]).status_code == 404
        assert len(gen.calls) == 1 and gen.calls[0] == body["prompt"] and emb.media_calls == 1
        assert web.post(f"/api/generations/{id_}/save", headers=headers).json() == done
        assert emb.media_calls == 1 and store.count() == 1
        assert search(web, body, headers).json()["items"][0]["id"] == item["id"]
        assert web.post(f"/api/generations/{id_}/discard", headers=headers).status_code == 409
        assert store.count() == 1 and web.get(item["media_url"]).status_code == 200
    store.close()


def test_rejected_candidates_remain_diagnostic_and_search_does_not_generate(tmp_path):
    s = settings(tmp_path)
    store = Store(s, QdrantClient(":memory:"))
    store.ensure()
    point_id = str(uuid.uuid4())
    store.upsert(point_id, [0., 1., 0.], dict(kind="image", title="coffee beans", source_name="coffee.jpg",
        media_path="coffee.jpg", thumbnail_path="thumb.jpg", start_seconds=None, end_seconds=None))
    gen = FakeGenerator()
    with TestClient(create_app(s, store, FakeEmbedder(), gen)) as web:
        headers, body = session(web), approved("a zebra")
        result = search(web, body, headers).json()
        assert result["items"][0]["id"] == point_id and result["best_score"] == 0
        assert not result["match_found"] and result["generation_available"]
        assert result["match_basis"] == "related"
        assert result["items"][0]["match_type"] == "related"
        assert gen.calls == []
        video = approved("a video", kind="video")
        assert not search(web, video, headers).json()["generation_available"]
        assert web.post("/api/generations", json=video, headers=headers).status_code == 422
    store.close()


def test_name_match_below_cosine_heuristic_is_a_match_without_generating(tmp_path):
    s = settings(tmp_path, match_threshold=.35)
    store = Store(s, QdrantClient(":memory:"))
    store.ensure()
    point_id = str(uuid.uuid4())
    # Reproduce the measured Qwen coffee score without a paid model call.
    score = .346449
    store.upsert(point_id, [score, math.sqrt(1 - score * score), 0.],
        dict(kind="image", title="coffee beans", source_name="coffee-beans.jpg",
             media_path="coffee.jpg", thumbnail_path="thumb.jpg"))
    gen = FakeGenerator()
    with TestClient(create_app(s, store, FakeEmbedder(), gen)) as web:
        headers, body = session(web), approved("coffee")
        response = search(web, body, headers)
        assert response.status_code == 200
        result = response.json()
        assert result["match_found"] is True and result["match_basis"] == "named"
        assert result["matched_count"] == 1
        assert result["items"][0]["id"] == point_id
        assert result["items"][0]["match_type"] == "named"
        assert result["items"][0]["score"] == pytest.approx(score)
        assert result["items"][0]["matched_terms"] == ["coffee"]
        assert gen.calls == []
    store.close()


def test_user_can_choose_creation_even_when_a_match_exists(tmp_path):
    s = settings(tmp_path)
    store = Store(s, QdrantClient(":memory:"))
    store.ensure()
    store.upsert(str(uuid.uuid4()), [1., 0., 0.], dict(kind="image", title="castle", source_name="castle.jpg",
        media_path="castle.jpg", thumbnail_path="thumb.jpg"))
    gen = FakeGenerator()
    with TestClient(create_app(s, store, FakeEmbedder(), gen)) as web:
        headers, body = session(web), approved()
        assert search(web, body, headers).json()["match_found"]
        response = web.post("/api/generations", json=body, headers=headers)
        assert response.status_code == 202
        assert completed(web, response.json()["id"])["status"] == "ready"
        assert store.count() == 1 and len(gen.calls) == 1
    store.close()


def test_discard_removes_private_image_and_never_indexes_it(tmp_path):
    s = settings(tmp_path)
    store = Store(s, QdrantClient(":memory:"))
    emb, gen = FakeEmbedder(), FakeGenerator()
    with TestClient(create_app(s, store, emb, gen)) as web:
        headers, body = session(web), approved()
        search(web, body, headers)
        id_ = web.post("/api/generations", json=body, headers=headers).json()["id"]
        ready = completed(web, id_)
        discarded = web.post(f"/api/generations/{id_}/discard", headers=headers)
        assert discarded.json()["status"] == "discarded"
        assert web.post(f"/api/generations/{id_}/discard", headers=headers).json()["status"] == "discarded"
        assert web.post(f"/api/generations/{id_}/save", headers=headers).status_code == 409
        assert web.get(ready["preview"]["media_url"]).status_code == 404
        assert not (s.data_dir / ".generation-previews" / id_).exists()
        assert store.count() == 0 and emb.media_calls == 0
    store.close()


def test_owner_isolation_csrf_and_owned_recent_search_are_required(tmp_path):
    s = settings(tmp_path, public_demo=True)
    store = Store(s, QdrantClient(":memory:"))
    with TestClient(create_app(s, store, FakeEmbedder(), FakeGenerator())) as web:
        body = approved()
        assert web.post("/api/search", json=body).status_code == 403
        headers = session(web)
        assert search(web, body, {**headers, "Origin": "https://evil.invalid"}).status_code == 403
        assert web.post("/api/generations", json=body, headers=headers).status_code == 409
        assert search(web, body, headers).status_code == 200
        id_ = web.post("/api/generations", json=body, headers=headers).json()["id"]
        ready = completed(web, id_)
        for action in ("save", "discard"):
            assert web.post(f"/api/generations/{id_}/{action}").status_code == 403
            assert web.post(f"/api/generations/{id_}/{action}", headers={**headers, "Origin": "https://evil.invalid"}).status_code == 403
        web.cookies.clear()
        stranger = session(web)
        assert web.get("/api/generations/" + id_).status_code == 404
        assert web.get(ready["preview"]["media_url"]).status_code == 404
        for action in ("save", "discard"):
            assert web.post(f"/api/generations/{id_}/{action}", headers=stranger).status_code == 404
        assert web.post("/api/generations", json=body, headers=stranger).status_code == 409
        assert web.get("/api/gallery").json()["items"] == []
        assert web.get("/media/../demo.sqlite3").status_code == 404
        assert web.get("/api/status").headers["cache-control"] == "no-store"
    store.close()


def test_approval_id_is_bound_to_prompt_and_query_and_retries_do_not_spend_twice(tmp_path):
    s = settings(tmp_path, max_generations_per_day=1)
    store = Store(s, QdrantClient(":memory:"))
    hold = threading.Event()
    gen = FakeGenerator(hold)
    with TestClient(create_app(s, store, FakeEmbedder(), gen)) as web:
        headers, body = session(web), approved("first castle")
        search(web, body, headers)
        id_ = web.post("/api/generations", json=body, headers=headers).json()["id"]
        assert web.post("/api/generations", json=body, headers=headers).json()["id"] == id_
        changed = {**body, "prompt": "an unapproved different description"}
        assert web.post("/api/generations", json=changed, headers=headers).status_code == 409
        second_query = {**body, "query": "a second castle"}
        search(web, second_query, headers)
        assert web.post("/api/generations", json=second_query, headers=headers).status_code == 409
        second_request = {**body, "request_id": str(uuid.uuid4())}
        assert web.post("/api/generations", json=second_request, headers=headers).status_code == 429
        hold.set()
        assert completed(web, id_)["status"] == "ready"
        assert len(gen.calls) == 1
    ledger = Ledger(s.data_dir)
    try:
        with pytest.raises(BudgetExceeded):
            ledger.charge("generation", "new-visitor", 1, 86400)
    finally:
        ledger.close()
        store.close()


def test_index_failure_keeps_preview_and_retry_reuses_embedding(tmp_path, monkeypatch):
    s = settings(tmp_path)
    store = Store(s, QdrantClient(":memory:"))
    emb, gen = FakeEmbedder(), FakeGenerator()
    original_upsert = store.upsert
    upserts = []
    def flaky(*args):
        upserts.append(args[0])
        if len(upserts) == 1:
            raise RuntimeError("private upstream diagnostics must not leak")
        return original_upsert(*args)
    monkeypatch.setattr(store, "upsert", flaky)
    with TestClient(create_app(s, store, emb, gen)) as web:
        headers, body = session(web), approved()
        search(web, body, headers)
        id_ = web.post("/api/generations", json=body, headers=headers).json()["id"]
        ready = completed(web, id_)
        failed = web.post(f"/api/generations/{id_}/save", headers=headers)
        assert failed.status_code == 503 and "private upstream" not in failed.text
        assert completed(web, id_)["status"] == "ready"
        assert web.get(ready["preview"]["media_url"]).status_code == 200
        assert web.post(f"/api/generations/{id_}/save", headers=headers).json()["status"] == "saved"
        assert len(upserts) == 2 and upserts[0] == upserts[1]
        assert emb.media_calls == 1 and len(gen.calls) == 1 and store.count() == 1
    store.close()


def test_legacy_succeeded_jobs_are_kept_as_saved_and_saving_recovers(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    old = sqlite3.connect(data / "demo.sqlite3")
    old.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, owner TEXT, key TEXT, query TEXT, status TEXT, result TEXT, created REAL)")
    id_ = str(uuid.uuid4())
    item = {"id": str(uuid.uuid4()), "media_url": "/media/existing.jpg"}
    old.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?)", (id_, "owner", "old-key", "old prompt", "succeeded", json.dumps({"item": item}), time.time()))
    old.commit()
    old.close()
    ledger = Ledger(data)
    assert ledger.get_job(id_, "owner") == {"id": id_, "status": "saved", "prompt": "old prompt", "item": item}
    assert ledger.db.execute("SELECT status FROM jobs WHERE id=?", (id_,)).fetchone()[0] == "succeeded"
    ledger.db.execute("UPDATE jobs SET status='saving' WHERE id=?", (id_,))
    ledger.db.commit()
    ledger.close()
    ledger = Ledger(data)
    assert ledger.get_job(id_, "owner")["status"] == "ready"
    ledger.close()


def test_generator_validates_actual_image_and_never_fetches_returned_url(tmp_path):
    s = settings(tmp_path)
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == "/v1/images/generations"
        body = json.loads(request.content)
        assert body["model"] == s.generation_model and body["n"] == 1
        assert body["size"] == "1024x1024" and body["response_format"] == "b64_json"
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})
    client = Generator(s, httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        assert client.image("a castle") == png()
    finally:
        client.close()
    assert len(calls) == 1
    for response in ({"data": [{"url": "http://internal.invalid/private"}]},
                     {"data": [{"b64_json": base64.b64encode(b"not-an-image").decode()}]}):
        client = Generator(s, httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))))
        try:
            with pytest.raises(GenerationError):
                client.image("a castle")
        finally:
            client.close()
    client = Generator(s, httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(400, json={"detail": "private upstream content"}))))
    try:
        with pytest.raises(GenerationError, match="declined this request") as rejected:
            client.image("a castle")
        assert "private upstream" not in str(rejected.value)
    finally:
        client.close()


def test_optional_demo_password_protects_media_and_apis(tmp_path):
    s = settings(tmp_path, demo_password="fixture-café")
    store = Store(s, QdrantClient(":memory:"))
    with TestClient(create_app(s, store, FakeEmbedder(), FakeGenerator())) as web:
        assert web.get("/").status_code == 401
        assert web.get("/api/status").status_code == 401
        assert web.get("/media/any.jpg").status_code == 401
        credentials = base64.b64encode("demo:fixture-café".encode()).decode()
        assert web.get("/", headers={"Authorization": "Basic " + credentials}).status_code == 200
        malformed = base64.b64encode("demo:wrong-café".encode()).decode()
        assert web.get("/", headers={"Authorization": "Basic " + malformed}).status_code == 401
    store.close()
