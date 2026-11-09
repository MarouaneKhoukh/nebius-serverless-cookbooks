#!/usr/bin/env python3
"""Create a resumable document embedding collection and query its saved vectors."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

MODEL = "Qwen/Qwen3-Embedding-0.6B"
DIMENSIONS = 1024
QUERY_INSTRUCTION = "Given a question, retrieve relevant passages from the document collection that answer it"


class RecipeError(Exception):
    """An actionable message that does not expose credentials."""


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value
    except (ValueError, OSError) as exc:
        raise RecipeError(f"Saved JSON is unreadable: {path}. Inspect it or use a new output directory.") from exc


def artwork() -> str:
    path = Path(__file__).resolve().parents[1] / "docs" / "brand" / "nebius-logo.svg"
    if not path.is_file():
        raise RecipeError("Bundled docs/brand/nebius-logo.svg is missing")
    return path.read_text(encoding="utf-8")


def report(path: Path, title: str, summary: str, fields: list[str], records: list[dict]) -> None:
    headers = "".join("<th>" + html.escape(name) + "</th>" for name in fields)
    body = "".join("<tr>" + "".join("<td>" + html.escape(str(record.get(field, ""))) + "</td>" for field in fields) + "</tr>" for record in records)
    atomic_write(path, "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>" + html.escape(title)
        + "</title><style>body{font:16px/1.55 system-ui;color:#24271f;background:#f7f7ef;padding:32px;margin:0}main{max-width:1180px;margin:auto}header{display:flex;gap:24px;align-items:center;flex-wrap:wrap}header svg{width:140px;height:auto}h1{font-size:32px;line-height:1.15}.summary{padding:20px;background:#e1f58a;border-radius:12px}.table{overflow:auto;background:white;border:1px solid #d8ddce;border-radius:12px}table{border-collapse:collapse;width:100%}th,td{text-align:left;vertical-align:top;padding:14px;border-bottom:1px solid #e1e4db}th{background:#ecefe3}footer{margin-top:24px;color:#555a4c}</style><main><header>"
        + artwork() + "<strong>Powered by Nebius Serverless AI</strong></header><h1>" + html.escape(title) + "</h1><p class='summary'>" + html.escape(summary)
        + "</p><div class='table'><table><thead><tr>" + headers + "</tr></thead><tbody>" + body
        + "</tbody></table></div><footer>Saved model results.</footer></main></html>")


def load_chunks(directory: Path, words: int = 160) -> list[dict]:
    if not directory.is_dir() or not 10 <= words <= 500:
        raise RecipeError("Input must be a document directory; --chunk-words must be between 10 and 500")
    chunks = []
    paths = sorted(path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in {".txt", ".md"})
    if not paths:
        raise RecipeError("Input directory has no .txt or .md documents")
    for path in paths:
        if path.is_symlink():
            raise RecipeError(f"Replace the symlink with a deliberate input file: {path.name}")
        if path.stat().st_size > 5 * 1024 * 1024:
            raise RecipeError(f"Document exceeds the 5 MiB starter limit: {path.name}. Split it into smaller text files.")
        try:
            content = path.read_text(encoding="utf-8").strip()
        except UnicodeError:
            raise RecipeError(f"Document is not UTF-8 text: {path.name}") from None
        if not content:
            raise RecipeError(f"Document is empty: {path.name}")
        relative = path.relative_to(directory).as_posix()
        paragraphs = [part.split() for part in re.split(r"\n\s*\n", content) if part.strip()]
        packed: list[str] = []
        current: list[str] = []
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
        for index, text in enumerate(packed):
            chunks.append({"id": digest({"source": relative, "chunk_index": index, "text": text}), "document_id": digest(relative), "source": relative, "chunk_index": index, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest()})
    return chunks


def unit_vector(value: object, dimensions: int) -> list[float]:
    if not isinstance(value, list) or len(value) != dimensions:
        raise RecipeError(f"Embedding must have exactly {dimensions} dimensions")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise RecipeError("Embedding contains non-numeric or non-finite values")
    norm = math.sqrt(sum(float(x) * float(x) for x in value))
    if not math.isfinite(norm) or norm <= 0:
        raise RecipeError("Embedding has zero or invalid length")
    return [float(x) / norm for x in value]


class Endpoint:
    def __init__(self, base: str, token: str, *, attempts: int = 3):
        base = base.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        parsed = urllib.parse.urlparse(base)
        loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not parsed.hostname or (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback)) or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RecipeError("BASE_URL must be an HTTPS Endpoint URL without embedded credentials or query parameters")
        if not token:
            raise RecipeError("ENDPOINT_TOKEN is missing. Run through scripts/endpoint.py.")
        self.base, self._token, self.attempts = base, token, attempts

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("BASE_URL", ""), os.environ.get("ENDPOINT_TOKEN", ""))

    def request(self, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json"}, method="GET" if body is None else "POST")
        for attempt in range(self.attempts):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    result = json.load(response)
                if not isinstance(result, dict):
                    raise RecipeError("Endpoint returned a non-object response")
                return result
            except urllib.error.HTTPError as exc:
                if exc.code in {401, 403}:
                    raise RecipeError(f"Endpoint returned HTTP {exc.code}; verify authentication. Credentials were not retried.") from None
                if exc.code not in {408, 429, 500, 502, 503, 504}:
                    raise RecipeError(f"Endpoint returned HTTP {exc.code}; check model/request configuration.") from None
                message = f"Endpoint returned HTTP {exc.code}"
            except (urllib.error.URLError, OSError, TimeoutError):
                message = "Endpoint could not be reached"
            except (ValueError, UnicodeError):
                raise RecipeError("Endpoint returned invalid JSON") from None
            if attempt + 1 == self.attempts:
                raise RecipeError(message + ". Saved chunks are safe. Restore the Endpoint and rerun the same index command.")
            time.sleep(min(2 ** attempt, 4))
        raise AssertionError("unreachable")

    def ready(self, model: str) -> None:
        result = self.request("/v1/models")
        if model not in [entry.get("id") for entry in result.get("data", []) if isinstance(entry, dict)]:
            raise RecipeError("Endpoint is ready but serves a different model. Use this cookbook's embedding configuration.")

    def embed(self, texts: list[str], model: str, dimensions: int) -> list[list[float]]:
        if dimensions != DIMENSIONS:
            raise RecipeError("This recipe uses the model's native 1024-dimensional output")
        # The pinned vLLM runtime rejects an explicit dimensions override for this
        # model, including its native size. Omit it and validate the native result.
        result = self.request("/v1/embeddings", {"model": model, "input": texts, "encoding_format": "float"})
        data = result.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise RecipeError("Embedding API returned an incomplete batch; no chunks from it were marked complete")
        indexed = {}
        for entry in data:
            if not isinstance(entry, dict) or type(entry.get("index")) is not int:
                raise RecipeError("Embedding API returned missing or invalid item indexes")
            index = entry["index"]
            if index < 0 or index >= len(texts) or index in indexed:
                raise RecipeError("Embedding API returned duplicate or out-of-range item indexes")
            indexed[index] = unit_vector(entry.get("embedding"), dimensions)
        return [indexed[index] for index in range(len(texts))]


def load_saved(chunks: list[dict], output: Path, fingerprint: str, dimensions: int) -> list[dict]:
    records = []
    for chunk in chunks:
        path = output / "items" / (chunk["id"] + ".json")
        if not path.exists():
            continue
        record = read_json(path)
        if record.get("fingerprint") != fingerprint or any(record.get(key) != chunk[key] for key in chunk):
            raise RecipeError("Saved chunk does not match this input/model; use a new output directory")
        unit_vector(record.get("vector"), dimensions)
        records.append(record)
    return records


def export_index(chunks: list[dict], records: list[dict], output: Path, settings: dict, fingerprint: str) -> dict:
    atomic_write(output / "vectors.jsonl", "".join(json.dumps({"id": record["id"], "vector": record["vector"]}) + "\n" for record in records))
    atomic_write(output / "metadata.jsonl", "".join(json.dumps({key: record[key] for key in ("id", "document_id", "source", "chunk_index", "text", "text_sha256")}, ensure_ascii=False) + "\n" for record in records))
    manifest = {"schema": 1, "fingerprint": fingerprint, "model": settings["model"], "model_revision": settings["model_revision"], "dimensions": settings["dimensions"], "documents": len({chunk["source"] for chunk in chunks}), "chunks_total": len(chunks), "chunks_saved": len(records), "remaining": len(chunks) - len(records), "complete": len(records) == len(chunks), "chunk_words": settings["chunk_words"], "vectors": "vectors.jsonl", "metadata": "metadata.jsonl"}
    write_json(output / "manifest.json", manifest)
    report(output / "index.html", "Saved Document Embeddings", f"{len(records)} / {len(chunks)} chunks saved · {manifest['documents']} documents · {settings['dimensions']}-dimensional vectors", ["source", "chunk_index", "text"], records)
    return manifest


def index_collection(chunks: list[dict], output: Path, settings: dict, embed, *, batch_size: int = 2, limit: int | None = None) -> dict:
    if not 1 <= batch_size <= 32 or (limit is not None and limit < 1):
        raise RecipeError("Batch size must be 1–32; --limit-chunks must be positive")
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RecipeError("Another index process is using this output directory") from None
        fingerprint = digest({"schema": 1, "chunks": chunks, "settings": settings})
        state = output / "run.json"
        if state.exists():
            if read_json(state).get("fingerprint") != fingerprint:
                raise RecipeError("Input, chunking or model settings changed. Use a new --output-dir; existing vectors were preserved.")
        else:
            write_json(state, {"fingerprint": fingerprint, "settings": settings})
        records = load_saved(chunks, output, fingerprint, settings["dimensions"])
        done = {record["id"] for record in records}
        pending = [chunk for chunk in chunks if chunk["id"] not in done]
        for chunk in chunks:
            if chunk["id"] in done:
                print(f"saved: {chunk['source']} chunk {chunk['chunk_index']}", flush=True)
        if limit is not None:
            pending = pending[:limit]
        try:
            for start in range(0, len(pending), batch_size):
                batch = pending[start:start + batch_size]
                vectors = embed([chunk["text"] for chunk in batch], settings["model"], settings["dimensions"])
                if len(vectors) != len(batch):
                    raise RecipeError("Embedding function returned an incomplete batch")
                vectors = [unit_vector(vector, settings["dimensions"]) for vector in vectors]
                for chunk, vector in zip(batch, vectors):
                    write_json(output / "items" / (chunk["id"] + ".json"), {**chunk, "vector": vector, "fingerprint": fingerprint})
                    print(f"completed: {chunk['source']} chunk {chunk['chunk_index']}", flush=True)
        finally:
            records = load_saved(chunks, output, fingerprint, settings["dimensions"])
            manifest = export_index(chunks, records, output, settings, fingerprint)
        return manifest


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise RecipeError("Query and document embedding dimensions differ")
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def query_collection(output: Path, text: str, endpoint: Endpoint, *, top_k: int = 3) -> list[dict]:
    if not text.strip() or len(text.split()) > 500 or not 1 <= top_k <= 20:
        raise RecipeError("Supply a non-empty query of at most 500 words and --top-k 1–20")
    manifest = read_json(output / "manifest.json")
    if not manifest.get("complete"):
        raise RecipeError("Index is incomplete. Finish the index command before querying it.")
    settings = read_json(output / "run.json")["settings"]
    if settings["model"] != manifest.get("model"):
        raise RecipeError("Saved index model metadata is inconsistent")
    records = []
    for path in sorted((output / "items").glob("*.json")):
        record = read_json(path)
        if record.get("fingerprint") != manifest["fingerprint"]:
            raise RecipeError("Saved vectors belong to a different index")
        record["vector"] = unit_vector(record.get("vector"), manifest["dimensions"])
        records.append(record)
    if len(records) != manifest["chunks_saved"]:
        raise RecipeError("Saved chunk count does not match the manifest")
    endpoint.ready(manifest["model"])
    instructed = f"Instruct: {QUERY_INSTRUCTION}\nQuery:{text.strip()}"
    query = endpoint.embed([instructed], manifest["model"], manifest["dimensions"])[0]
    ranked = sorted(({"id": record["id"], "source": record["source"], "chunk_index": record["chunk_index"], "text": record["text"], "similarity": cosine(query, record["vector"])} for record in records), key=lambda record: (-record["similarity"], record["id"]))[:top_k]
    write_json(output / "search.json", {"query": text, "instruction": QUERY_INSTRUCTION, "index_fingerprint": manifest["fingerprint"], "matches": ranked})
    report(output / "search.html", "Search Documents by Meaning", f"Query: {text} · {manifest['chunks_saved']} saved chunks · {manifest['model']}", ["source", "similarity", "text"], ranked)
    return ranked


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index", help="Embed .txt/.md documents and save vectors")
    index.add_argument("--input-dir", type=Path, default=Path("data/documents"))
    index.add_argument("--output-dir", type=Path, default=Path("results"))
    index.add_argument("--model", default=MODEL)
    index.add_argument("--model-revision", default=os.environ.get("MODEL_REVISION", ""))
    index.add_argument("--dimensions", type=int, choices=[DIMENSIONS], default=DIMENSIONS, help="Native size used by this recipe (1024)")
    index.add_argument("--chunk-words", type=int, default=160)
    index.add_argument("--batch-size", type=int, default=2)
    index.add_argument("--limit-chunks", type=int)
    query = sub.add_parser("query", help="Embed one query and search saved vectors locally")
    query.add_argument("--output-dir", type=Path, default=Path("results"))
    query.add_argument("--text", required=True)
    query.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        artwork()
        endpoint = Endpoint.from_environment()
        if args.command == "index":
            if args.dimensions != DIMENSIONS:
                raise RecipeError("This recipe uses the native 1024-dimensional model output")
            chunks = load_chunks(args.input_dir, args.chunk_words)
            settings = {"model": args.model, "model_revision": args.model_revision, "dimensions": args.dimensions, "chunk_words": args.chunk_words}
            endpoint.ready(args.model)
            result = index_collection(chunks, args.output_dir, settings, endpoint.embed, batch_size=args.batch_size, limit=args.limit_chunks)
            print(f"Saved {result['chunks_saved']} / {result['chunks_total']} chunks; dimensions={result['dimensions']}; complete={result['complete']}")
            print(f"Wrote {args.output_dir / 'vectors.jsonl'} and {args.output_dir / 'index.html'}")
        else:
            ranked = query_collection(args.output_dir, args.text, endpoint, top_k=args.top_k)
            for rank, record in enumerate(ranked, 1):
                print(f"{rank}. {record['source']} — cosine {record['similarity']:.4f}")
            print(f"Wrote {args.output_dir / 'search.json'} and {args.output_dir / 'search.html'}")
        return 0
    except (RecipeError, OSError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
