"""Offline checks: mock embeddings are never evidence of Qwen relevance."""
from dataclasses import replace
import json
from pathlib import Path
import uuid

from fastapi.testclient import TestClient
import httpx
from PIL import Image
import pytest
from qdrant_client import QdrantClient

from media_search.app import create_app
from media_search.config import Settings
from media_search.embedding import Embedder, EmbeddingError
from media_search.store import Store


def config(tmp_path):
    return Settings(data_dir=tmp_path / "data", embedding_url="https://example.invalid",
                    embedding_token="test-only-placeholder", dimensions=3)


def record(path="item.jpg", kind="image", title="a red circle"):
    return dict(kind=kind, title=title, source_name="untrusted <name>.png",
                media_path=path, thumbnail_path=path,
                start_seconds=0.0 if kind == "video" else None,
                end_seconds=8.0 if kind == "video" else None)


def test_text_and_media_use_the_same_qwen_protocol(tmp_path):
    requests = []
    def handle(request):
        assert request.url.path == "/v1/embeddings"
        assert request.headers["authorization"] == "Bearer test-only-placeholder"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"embedding": [3, 0, 4]}]})
    client = Embedder(config(tmp_path), httpx.Client(transport=httpx.MockTransport(handle)))
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"image-bytes")
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video-bytes")
    try:
        assert client.text("red circle") == [0.6, 0.0, 0.8]
        client.media(photo, "image")
        client.media(clip, "video")
    finally:
        client.close()
    for body in requests:
        assert body["continue_final_message"] is True
        assert body["add_special_tokens"] is True
        assert body["messages"][0] == requests[0]["messages"][0]
        assert body["messages"][-1] == requests[0]["messages"][-1]
        assert "input" not in body
        assert "photo.jpg" not in json.dumps(body)
    assert requests[1]["messages"][1]["content"][0]["image_url"]["url"] == "data:image/jpeg;base64,aW1hZ2UtYnl0ZXM="
    assert requests[2]["messages"][1]["content"][0]["video_url"]["url"] == "data:video/mp4;base64,dmlkZW8tYnl0ZXM="
    assert requests[2]["media_io_kwargs"] == {"video": {"num_frames": 8}}


@pytest.mark.parametrize("vector", [[0, 0, 0], [1, 2], [1, float("nan"), 2], [True, 0, 1], "bad"])
def test_reject_invalid_vectors(tmp_path, vector):
    client = Embedder(config(tmp_path), httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=json.dumps({"data": [{"embedding": vector}]})))))
    try:
        with pytest.raises(EmbeddingError):
            client.text("example")
    finally:
        client.close()


def test_error_does_not_echo_upstream_request_or_token(tmp_path):
    client = Embedder(config(tmp_path), httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(401, text="sensitive input test-only-placeholder"))))
    try:
        with pytest.raises(EmbeddingError, match="HTTP 401") as info:
            client.text("private query")
        assert "sensitive" not in str(info.value)
        assert "test-only" not in str(info.value)
    finally:
        client.close()


def test_persistent_collection_ranking_filters_and_schema(tmp_path):
    settings = config(tmp_path)
    location = str(tmp_path / "qdrant")
    store = Store(settings, QdrantClient(path=location))
    store.ensure()
    image_id, video_id = str(uuid.uuid4()), str(uuid.uuid4())
    store.upsert(image_id, [1., 0., 0.], record())
    store.upsert(video_id, [0., 1., 0.], record("clip.mp4", "video"))
    store.close()
    # A fresh client reopens disk-backed state, not an in-memory mock.
    client = QdrantClient(path=location)
    store = Store(settings, client)
    try:
        store.ensure()
        assert store.count() == 2
        assert store.search([1., 0., 0.])[0]["id"] == image_id
        assert store.search([0., 1., 0.])[0]["id"] == video_id
        assert [p["id"] for p in store.search([1., 0., 0.], "video")] == [video_id]
        assert store.search([0., 1., 0.], "video")[0]["start_seconds"] == 0
        assert len(store.gallery()) == 2
        with pytest.raises(ValueError, match="contract differs"):
            Store(replace(settings, model="a-different-model"), client).ensure()
    finally:
        store.close()


def test_gallery_search_and_range_playback(tmp_path):
    settings = config(tmp_path)
    root = settings.data_dir / "media"
    root.mkdir(parents=True)
    (root / "clip.mp4").write_bytes(b"0123456789")
    (settings.data_dir / ".env").write_text("private")
    store = Store(settings, QdrantClient(":memory:"))
    store.ensure()
    store.upsert(str(uuid.uuid4()), [0., 1., 0.], record("clip.mp4", "video"))
    class QueryEmbedder:
        def text(self, text):
            assert text == "a blue square"
            return [0., 1., 0.]
    try:
        with TestClient(create_app(settings, store, QueryEmbedder())) as web:
            assert web.get("/").status_code == 200
            assert web.get("/static/app.js").status_code == 200
            assert web.get("/api/status").json()["points"] == 1
            assert len(web.get("/api/gallery").json()["items"]) == 1
            results = web.post("/api/search", json={"query": "a blue square", "kind": "video"})
            assert results.status_code == 200
            assert results.json()["items"][0]["media_url"] == "/media/clip.mp4"
            assert "embedding_token" not in results.text
            partial = web.get("/media/clip.mp4", headers={"Range": "bytes=2-5"})
            assert partial.status_code == 206 and partial.content == b"2345"
            assert web.get("/media/%2e%2e/.env").status_code == 404
            assert web.post("/api/search", json={"query": "   "}).status_code == 422
            assert web.post("/api/search", json={"query": "x", "kind": "wrong"}).status_code == 422
            assert web.post("/api/search", json={"query": "x", "limit": 100}).status_code == 422
        with TestClient(create_app(replace(settings, embedding_token=""), store=store)) as web:
            assert len(web.get("/api/gallery").json()["items"]) == 1
            assert web.post("/api/search", json={"query": "a description"}).status_code == 503
    finally:
        store.close()


def test_reingestion_skips_cloud_requests_and_new_content_is_new_point(tmp_path, monkeypatch):
    import media_search.__main__ as cli
    settings = config(tmp_path)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    Image.new("RGB", (64, 64), "red").save(inputs / "picture.png")
    db_path = str(tmp_path / "db")
    calls = []
    class FakeEmbedder:
        def __init__(self, _): pass
        def media(self, path, kind):
            assert path.is_file() and kind == "image"
            calls.append(path)
            return [1., 0., 0.]
        def close(self): pass
    monkeypatch.setattr(cli, "Embedder", FakeEmbedder)
    monkeypatch.setattr(cli, "Store", lambda s: Store(s, QdrantClient(path=db_path)))
    assert cli.ingest(settings, inputs) == 0
    assert cli.ingest(settings, inputs) == 0
    assert len(calls) == 1
    Image.new("RGB", (64, 64), "blue").save(inputs / "picture.png")
    assert cli.ingest(settings, inputs) == 0
    assert len(calls) == 2
    store = Store(settings, QdrantClient(path=db_path))
    try:
        assert store.count() == 2
    finally:
        store.close()


def test_configuration_rejects_cleartext_remote_endpoint(tmp_path):
    with pytest.raises(ValueError, match="HTTPS"):
        replace(config(tmp_path), embedding_url="http://remote.invalid").require_embedding()
    with pytest.raises(ValueError, match="without /v1"):
        replace(config(tmp_path), embedding_url="https://example.invalid/v1").require_embedding()


def test_ingest_rejects_prepared_output_and_stops_after_endpoint_failure(tmp_path, monkeypatch):
    import media_search.__main__ as cli
    settings = config(tmp_path)
    prepared = settings.data_dir / "media"
    prepared.mkdir(parents=True)
    with pytest.raises(ValueError, match="separate"):
        cli.ingest(settings, prepared)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for index, color in enumerate(("red", "blue")):
        Image.new("RGB", (64, 64), color).save(inputs / f"{index}.png")
    calls = []
    class FailedEmbedder:
        def __init__(self, _): pass
        def media(self, path, kind):
            calls.append(path)
            raise EmbeddingError("Fixture Endpoint failure")
        def close(self): pass
    monkeypatch.setattr(cli, "Embedder", FailedEmbedder)
    monkeypatch.setattr(cli, "Store", lambda s: Store(s, QdrantClient(":memory:")))
    assert cli.ingest(settings, inputs) == 1
    assert len(calls) == 1
