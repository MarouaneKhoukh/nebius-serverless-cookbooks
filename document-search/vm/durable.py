"""Document-level durable indexing, independent of the encoder and storage.

Use one writer per dedicated store/prefix. This module does not provide a
distributed lock: do not run two indexing processes against the same prefix.
A document is complete only when its validated completion marker exists.
Local .pending-* files are uncommitted writes, never progress, and are ignored.

API:
  RunConfig(manifest_sha256, model, model_revision, dimensions,
            chunk_words=160, encoder_settings={})
  index_documents(documents, store, embed_fn, config, batch_size=16,
                  stop_after_documents=None, after_chunk_saved=None) -> stats
  inspect_documents(documents, store, config) -> {"stats": ..., "records": ...}
  load_records(documents, store, config, require_complete=True) -> records

embed_fn accepts a list of passage strings and returns one vector per passage.
stop_after_documents limits newly completed documents in this invocation.
after_chunk_saved(record) runs after verified persistence, before a document
marker; an exception deliberately leaves that chunk reusable after a restart.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
from urllib.parse import urlsplit


class DurableError(RuntimeError):
    """Invalid or incompatible durable state; preserve it and inspect it."""


def _json_bytes(value):
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise DurableError("State must contain finite, UTF-8 JSON values.") from exc


def _hash(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _strict_object(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("non-finite JSON constant")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except (ValueError, UnicodeError, AttributeError) as exc:
        raise DurableError("A saved object is not valid finite JSON.") from exc
    if not isinstance(value, dict):
        raise DurableError("A saved object must be a JSON object.")
    return value


def _key(value):
    if (not isinstance(value, str) or not value or value.startswith("/")
            or str(PurePosixPath(value)) != value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(ord(char) < 32 for char in value)):
        raise DurableError("Use a relative, normalized object key.")
    return value


class Store:
    """Bytes get/put/keys protocol with immutable, read-verified JSON writes."""

    def get(self, key):
        raise NotImplementedError

    def put(self, key, payload):
        raise NotImplementedError

    def keys(self):
        raise NotImplementedError

    def get_json(self, key):
        raw = self.get(key)
        return None if raw is None else _strict_object(raw)

    def put_json(self, key, value):
        payload = _json_bytes(value)
        self.put(key, payload)
        if self.get(key) != payload:
            raise DurableError("Saved object failed read-after-write verification.")


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mkdirs(path):
    if path.is_dir():
        return
    _mkdirs(path.parent)
    path.mkdir(exist_ok=True)
    _sync_directory(path)
    _sync_directory(path.parent)


class LocalStore(Store):
    """Atomic immutable files on durable disk. Single writer, not a lock."""

    def __init__(self, root):
        self.root = Path(root).expanduser().absolute()
        if self.root.is_symlink():
            raise DurableError("Choose a real output directory, not a symlink.")
        try:
            _mkdirs(self.root)
        except OSError as exc:
            raise DurableError("Cannot create the durable output directory.") from exc

    def _path(self, key):
        key = _key(key)
        path = self.root
        for part in key.split("/"):
            path = path / part
            if path.is_symlink():
                raise DurableError("Saved state contains a symlink.")
        return path

    def get(self, key):
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise DurableError("Cannot read a saved local object.") from exc

    def put(self, key, payload):
        path = self._path(key)
        if not isinstance(payload, bytes):
            raise DurableError("Store.put requires bytes.")
        existing = self.get(key)
        if existing is not None:
            if existing != payload:
                raise DurableError("Refusing to overwrite a different durable object.")
            return
        temporary = None
        try:
            _mkdirs(path.parent)
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            _sync_directory(path.parent)
        except OSError as exc:
            raise DurableError("Cannot durably save a local object.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def keys(self):
        result = []
        for path in self.root.rglob("*"):
            if path.is_symlink():
                raise DurableError("Saved state contains a symlink.")
            if path.is_file() and not path.name.startswith(".pending-"):
                result.append(path.relative_to(self.root).as_posix())
        return sorted(result)


class S3Store(Store):
    """Immutable objects in a dedicated S3 prefix; boto3 is imported on first I/O."""

    def __init__(self, uri, *, endpoint_url=None, client=None):
        parsed = urlsplit(uri)
        if (parsed.scheme != "s3" or not parsed.netloc
                or parsed.netloc != parsed.hostname
                or parsed.query or parsed.fragment):
            raise DurableError("Use s3://bucket/dedicated-prefix without credentials.")
        self.bucket = parsed.netloc
        self.prefix = _key(parsed.path.strip("/"))
        self.endpoint_url = os.environ.get("S3_ENDPOINT_URL") if endpoint_url is None else endpoint_url
        endpoint = urlsplit(self.endpoint_url or "")
        if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username
                or endpoint.password or endpoint.query or endpoint.fragment
                or endpoint.path not in {"", "/"}):
            raise DurableError("Set an explicit HTTPS S3 endpoint with S3_ENDPOINT_URL or endpoint_url.")
        self._client = client

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise DurableError("Install boto3 to use S3 storage.") from exc
            self._client = boto3.client("s3", endpoint_url=self.endpoint_url)
        return self._client

    def _full(self, key):
        return self.prefix + "/" + _key(key)

    def get(self, key):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._full(key))
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = str(response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "NotFound", "404"}:
                return None
            raise DurableError("S3 read failed; check endpoint, permissions and connectivity.") from exc
        stream = response["Body"]
        try:
            return stream.read()
        finally:
            stream.close()

    def put(self, key, payload):
        if not isinstance(payload, bytes):
            raise DurableError("Store.put requires bytes.")
        existing = self.get(key)
        if existing is not None:
            if existing != payload:
                raise DurableError("Refusing to overwrite a different durable object.")
            return
        try:
            self.client.put_object(Bucket=self.bucket, Key=self._full(key), Body=payload)
        except Exception as exc:
            raise DurableError("S3 write failed; check permissions and connectivity.") from exc

    def keys(self):
        result, token = [], None
        while True:
            arguments = {"Bucket": self.bucket, "Prefix": self.prefix + "/"}
            if token is not None:
                arguments["ContinuationToken"] = token
            try:
                response = self.client.list_objects_v2(**arguments)
            except Exception as exc:
                raise DurableError("S3 listing failed; check permissions and connectivity.") from exc
            for item in response.get("Contents", []):
                full = item["Key"]
                if not full.startswith(self.prefix + "/"):
                    raise DurableError("S3 listing escaped the selected prefix.")
                result.append(_key(full[len(self.prefix) + 1:]))
            if not response.get("IsTruncated"):
                return sorted(result)
            next_token = response.get("NextContinuationToken")
            if not next_token or next_token == token:
                raise DurableError("S3 pagination did not advance.")
            token = next_token


def open_store(uri, *, endpoint_url=None, client=None):
    if str(uri).startswith("s3://"):
        return S3Store(str(uri), endpoint_url=endpoint_url, client=client)
    if "://" in str(uri):
        raise DurableError("Use a local directory or s3://bucket/prefix.")
    return LocalStore(uri)


@dataclass(frozen=True)
class RunConfig:
    manifest_sha256: str
    model: str
    model_revision: str
    dimensions: int
    chunk_words: int = 160
    encoder_settings: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.manifest_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.manifest_sha256):
            raise DurableError("manifest_sha256 must be the pinned manifest SHA-256.")
        if not isinstance(self.model, str) or not self.model.strip():
            raise DurableError("Specify the embedding model.")
        if not isinstance(self.model_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", self.model_revision):
            raise DurableError("Pin model_revision to its 40-character commit SHA.")
        if type(self.dimensions) is not int or not 1 <= self.dimensions <= 32768:
            raise DurableError("dimensions must be a positive bounded integer.")
        if type(self.chunk_words) is not int or not 10 <= self.chunk_words <= 500:
            raise DurableError("chunk_words must be between 10 and 500.")
        if not isinstance(self.encoder_settings, dict):
            raise DurableError("encoder_settings must be a JSON object.")
        object.__setattr__(self, "encoder_settings",
                           json.loads(_json_bytes(self.encoder_settings)))


def _pack(text, words):
    """Same paragraph/word packing order as src/embed.py load_chunks."""
    paragraphs = [part.split() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    packed, current = [], []
    for paragraph in paragraphs:
        if len(current) + len(paragraph) > words and current:
            packed.append(" ".join(current))
            current = []
        while len(paragraph) > words:
            packed.append(" ".join(paragraph[:words]))
            paragraph = paragraph[words:]
        current.extend(paragraph)
    if current:
        packed.append(" ".join(current))
    return packed


def _plan(documents, config):
    if not isinstance(documents, list) or not documents:
        raise DurableError("Supply a nonempty document list.")
    seen, planned, all_chunks = set(), [], []
    for document in documents:
        if not isinstance(document, dict):
            raise DurableError("Each document must be an object.")
        for key in ("id", "title", "source_url", "text"):
            if not isinstance(document.get(key), str):
                raise DurableError("Documents require string id, title, source_url and text.")
        if not document["id"] or document["id"] in seen:
            raise DurableError("Document IDs must be nonempty and unique.")
        if not document["text"].strip() or len(document["text"].encode("utf-8")) > 5 * 1024 * 1024:
            raise DurableError("Documents must contain nonempty UTF-8 text of at most 5 MiB.")
        seen.add(document["id"])
        document_hash = _hash(document)
        document_key = hashlib.sha256(document["id"].encode("utf-8")).hexdigest()
        chunks = []
        for index, text in enumerate(_pack(document["text"], config.chunk_words)):
            chunk_id = _hash({"document_id": document["id"], "document_sha256": document_hash,
                              "chunk_index": index, "text": text})
            chunk = {"id": chunk_id, "document_id": document["id"], "source": document["id"],
                     "title": document["title"], "source_url": document["source_url"],
                     "document_sha256": document_hash, "chunk_index": index, "text": text,
                     "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
            chunks.append({"key": f"chunks/{document_key}/{chunk_id}.json", "metadata": chunk})
        planned.append({"id": document["id"], "document_sha256": document_hash,
                        "marker_key": f"documents/{document_key}.json", "chunks": chunks})
        all_chunks.extend(chunks)
    settings = {"model": config.model, "model_revision": config.model_revision,
                "dimensions": config.dimensions, "chunk_words": config.chunk_words,
                "chunking": "paragraph_word_pack_v1", "encoder_settings": config.encoder_settings}
    descriptor = {"schema": 1, "manifest_sha256": config.manifest_sha256, "settings": settings,
                  "documents": [{"id": item["id"], "document_sha256": item["document_sha256"],
                                 "chunk_ids": [c["metadata"]["id"] for c in item["chunks"]]}
                                for item in planned]}
    fingerprint = _hash(descriptor)
    return {"descriptor": {**descriptor, "run_fingerprint": fingerprint},
            "fingerprint": fingerprint, "documents": planned, "chunks": all_chunks}


def _vector(value, dimensions):
    if (not isinstance(value, list) or len(value) != dimensions
            or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value)):
        raise DurableError("A vector has wrong dimensions or non-numeric values.")
    try:
        converted = [float(x) for x in value]
        norm = math.hypot(*converted)
    except (OverflowError, ValueError) as exc:
        raise DurableError("A vector contains invalid numeric values.") from exc
    if any(not math.isfinite(x) for x in converted) or not math.isfinite(norm) or norm <= 0:
        raise DurableError("A vector has non-finite values or zero/invalid length.")
    return converted


def _record(chunk, vector, plan):
    result = {**chunk["metadata"], "schema": 1, "run_fingerprint": plan["fingerprint"],
              "vector": vector}
    return {**result, "record_sha256": _hash(result)}


def _validate_record(record, chunk, plan, config):
    expected = {**chunk["metadata"], "schema": 1, "run_fingerprint": plan["fingerprint"]}
    if not isinstance(record, dict) or set(record) != set(expected) | {"vector", "record_sha256"}:
        raise DurableError("Saved chunk has missing or unexpected fields.")
    if any(record.get(key) != value for key, value in expected.items()):
        raise DurableError("Saved chunk belongs to different text, document or configuration.")
    _vector(record["vector"], config.dimensions)
    body = {key: value for key, value in record.items() if key != "record_sha256"}
    if record["record_sha256"] != _hash(body):
        raise DurableError("Saved chunk checksum differs from its contents.")
    return record


def _marker(document, records, plan):
    chunks = []
    for chunk in document["chunks"]:
        record = records.get(chunk["metadata"]["id"])
        if record is None:
            raise DurableError("A completed document is missing a required chunk.")
        chunks.append({"id": record["id"], "record_sha256": record["record_sha256"]})
    body = {"schema": 1, "document_id": document["id"],
            "document_sha256": document["document_sha256"],
            "run_fingerprint": plan["fingerprint"], "chunks": chunks}
    return {**body, "marker_sha256": _hash(body)}


def _scan(plan, store, config):
    keys = store.keys()
    if len(set(keys)) != len(keys):
        raise DurableError("Store listing contains duplicate object keys.")
    if not keys:
        return {}, {}
    if "run.json" not in keys:
        raise DurableError("Durable objects exist without their run descriptor.")
    if store.get_json("run.json") != plan["descriptor"]:
        raise DurableError("Manifest, input, model, encoder or chunk settings changed. Use a new store/prefix.")
    chunks = {item["key"]: item for item in plan["chunks"]}
    markers = {item["marker_key"]: item for item in plan["documents"]}
    if set(keys) - ({"run.json"} | set(chunks) | set(markers)):
        raise DurableError("Unexpected objects exist in this dedicated store/prefix.")
    records, completed = {}, {}
    for key in sorted(set(keys) & set(chunks)):
        record = _validate_record(store.get_json(key), chunks[key], plan, config)
        records[record["id"]] = record
    for key in sorted(set(keys) & set(markers)):
        document = markers[key]
        marker = store.get_json(key)
        if marker != _marker(document, records, plan):
            raise DurableError("Document completion marker is corrupt or incompatible.")
        completed[document["id"]] = marker
    return records, completed


def _stats(plan, records, completed, reused_chunks, reused_documents, times, started):
    document_count, chunk_count = len(plan["documents"]), len(plan["chunks"])
    return {"run_fingerprint": plan["fingerprint"],
            "documents_total": document_count, "documents_completed": len(completed),
            "documents_reused": reused_documents, "documents_new": len(completed) - reused_documents,
            "documents_remaining": document_count - len(completed),
            "chunks_total": chunk_count, "chunks_saved": len(records),
            "chunks_reused": reused_chunks, "chunks_new": len(records) - reused_chunks,
            "chunks_remaining": chunk_count - len(records),
            "complete": len(completed) == document_count and len(records) == chunk_count,
            **times, "wall_seconds": time.perf_counter() - started}


def _fresh_times():
    return {"scan_seconds": 0.0, "embedding_seconds": 0.0, "save_seconds": 0.0}


@contextmanager
def _timed(times, key):
    started = time.perf_counter()
    try:
        yield
    finally:
        times[key] += time.perf_counter() - started


def inspect_documents(documents, store, config):
    started, times = time.perf_counter(), _fresh_times()
    with _timed(times, "scan_seconds"):
        plan = _plan(documents, config)
        records, completed = _scan(plan, store, config)
    ordered = [records[c["metadata"]["id"]] for c in plan["chunks"] if c["metadata"]["id"] in records]
    return {"stats": _stats(plan, records, completed, len(records), len(completed), times, started),
            "records": ordered}


def load_records(documents, store, config, *, require_complete=True):
    inspected = inspect_documents(documents, store, config)
    if require_complete and not inspected["stats"]["complete"]:
        raise DurableError("The document collection is incomplete; finish indexing before querying.")
    return inspected["records"]


def index_documents(documents, store, embed_fn, config, *, batch_size=16,
                    stop_after_documents=None, after_chunk_saved=None):
    started, times = time.perf_counter(), _fresh_times()
    if type(batch_size) is not int or not 1 <= batch_size <= 1024:
        raise DurableError("batch_size must be between 1 and 1024.")
    if stop_after_documents is not None and (type(stop_after_documents) is not int or stop_after_documents < 1):
        raise DurableError("stop_after_documents must be a positive integer.")
    with _timed(times, "scan_seconds"):
        plan = _plan(documents, config)
        records, completed = _scan(plan, store, config)
    reused_chunks, reused_documents = len(records), len(completed)
    with _timed(times, "scan_seconds"):
        empty_store = not store.keys()
    if empty_store:
        with _timed(times, "save_seconds"):
            store.put_json("run.json", plan["descriptor"])
            if store.get_json("run.json") != plan["descriptor"]:
                raise DurableError("Run descriptor failed verification.")
    selected = [item for item in plan["documents"] if item["id"] not in completed]
    if stop_after_documents is not None:
        selected = selected[:stop_after_documents]
    by_document = {item["id"]: item for item in selected}

    def finish(document):
        with _timed(times, "save_seconds"):
            # Read every required object again before declaring this document done.
            for chunk in document["chunks"]:
                record = _validate_record(store.get_json(chunk["key"]), chunk, plan, config)
                records[record["id"]] = record
            marker = _marker(document, records, plan)
            store.put_json(document["marker_key"], marker)
            if store.get_json(document["marker_key"]) != marker:
                raise DurableError("Document marker failed read-after-write verification.")
            completed[document["id"]] = marker

    for document in selected:
        if all(chunk["metadata"]["id"] in records for chunk in document["chunks"]):
            finish(document)
    pending = [chunk for document in selected for chunk in document["chunks"]
               if chunk["metadata"]["id"] not in records]
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset:offset + batch_size]
        with _timed(times, "embedding_seconds"):
            values = embed_fn([chunk["metadata"]["text"] for chunk in batch])
            if not isinstance(values, (list, tuple)) or len(values) != len(batch):
                raise DurableError("Encoder returned an incomplete batch.")
            vectors = [_vector(value, config.dimensions) for value in values]
        for chunk, vector in zip(batch, vectors):
            record = _record(chunk, vector, plan)
            with _timed(times, "save_seconds"):
                store.put_json(chunk["key"], record)
                verified = _validate_record(store.get_json(chunk["key"]), chunk, plan, config)
                records[record["id"]] = verified
            if after_chunk_saved is not None:
                after_chunk_saved(json.loads(_json_bytes(verified)))
            document = by_document[record["document_id"]]
            if document["id"] not in completed and all(c["metadata"]["id"] in records for c in document["chunks"]):
                finish(document)
    with _timed(times, "scan_seconds"):
        records, completed = _scan(plan, store, config)
    return _stats(plan, records, completed, reused_chunks, reused_documents, times, started)
