"""Prepare and verify 1,000 distinct, licensed Dolly reference passages.

Only source ``context`` fields are indexed. Instructions supply display titles;
responses are never included in the documents. The original 55-document Python
corpus remains a separate example.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.request

DATA = Path(__file__).resolve().parent / "data"
SOURCE_PATH = DATA / "source.json"
FILES = {"documents.jsonl", "manifest.json", "LICENSE", "SOURCE.md"}
MAX_SOURCE_BYTES = 25 * 1024 * 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON: {path.name}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return result


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _chunk_count(text: str, words: int = 160) -> int:
    """Count the existing recipe's paragraph-aware, non-overlapping chunks."""
    count, current = 0, 0
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        size = len(paragraph.split())
        if not size:
            continue
        if current and current + size > words:
            count, current = count + 1, 0
        while size > words:
            count, size = count + 1, size - words
        current += size
    return count + bool(current)


def _select(raw: bytes, source: dict) -> tuple[list[dict], list[dict]]:
    selection = source["selection"]
    count, minimum = selection["count"], selection["minimum_words"]
    if not isinstance(count, int) or not 1 <= count <= 1000 or minimum < 1:
        raise ValueError("Invalid selection bounds.")
    seen, documents, metadata = set(), [], []
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise ValueError("Dataset is not UTF-8.") from exc
    for line_number, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid dataset JSON at source line {line_number}.") from exc
        text = row.get("context", "")
        if not isinstance(text, str) or len(text.split()) < minimum:
            continue
        normalized_sha = sha256(" ".join(text.split()).encode("utf-8"))
        if normalized_sha in seen:
            continue
        seen.add(normalized_sha)
        instruction = row.get("instruction", "")
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError(f"Missing display instruction at source line {line_number}.")
        identifier = f"dolly-context-L{line_number:05d}"
        title = " ".join(instruction.split())[:160]
        url = source["source"]["view_url"] + f"#L{line_number}"
        documents.append({"id": identifier, "title": title, "source_url": url, "text": text})
        metadata.append({"id": identifier, "title": title, "source_url": url,
                         "source_line": line_number, "record_sha256": sha256(line.encode("utf-8")),
                         "text_sha256": sha256(text.encode("utf-8")),
                         "normalized_text_sha256": normalized_sha,
                         "category": row.get("category", ""),
                         "words": len(text.split()), "bytes": len(text.encode("utf-8"))})
        if len(documents) == count:
            break
    if len(documents) != count:
        raise ValueError(f"Dataset contains fewer than {count} eligible distinct passages.")
    return documents, metadata


def _fetch_source(source: dict, cache: Path, fetch=None) -> bytes:
    expected = source["source"]
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (expected["sha256"] + ".jsonl")
    if target.is_symlink():
        raise ValueError("Dataset cache must not be a symlink.")
    raw = target.read_bytes() if target.is_file() else b""
    if sha256(raw) != expected["sha256"]:
        if fetch is None:
            request = urllib.request.Request(expected["url"], headers={"User-Agent": "nebius-cookbooks"})
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read(MAX_SOURCE_BYTES + 1)
        else:
            raw = fetch(expected["url"])
        if (len(raw) > MAX_SOURCE_BYTES or len(raw) != expected["bytes"]
                or sha256(raw) != expected["sha256"]):
            raise ValueError("Dataset size/checksum differs from the pinned source.")
        _write(target, raw)
    return raw


def prepare(output_dir: Path, cache_dir: Path, *, source_path: Path = SOURCE_PATH, fetch=None) -> dict:
    """Download once, verify the pinned selection, and write four portable files.

    Preparation timing belongs in the caller's run log, not this immutable
    manifest. Existing unrelated files are never overwritten or deleted.
    """
    output, cache, source_path = Path(output_dir), Path(cache_dir), Path(source_path)
    source = _read_json(source_path)
    if output.is_symlink():
        raise ValueError("Output directory must not be a symlink.")
    if output.exists() and (not output.is_dir() or any(p.name not in FILES or p.is_symlink() or not p.is_file() for p in output.iterdir())):
        raise ValueError("Output directory contains unrelated files; choose a new directory.")
    license_bytes = (source_path.parent / "LICENSE").read_bytes()
    card = (source_path.parent / "DATASET_CARD.md").read_bytes()
    attribution = (source_path.parent / "SOURCE.md").read_bytes()
    if sha256(license_bytes) != source["license"]["sha256"]:
        raise ValueError("Bundled license checksum differs from the manifest.")
    if sha256(card) != source["source"]["card_sha256"] or b"license: cc-by-sa-3.0" not in card:
        raise ValueError("Bundled dataset card checksum/license differs from the pinned source.")
    if sha256(attribution) != source["attribution_sha256"]:
        raise ValueError("Bundled attribution checksum differs from the manifest.")
    raw = _fetch_source(source, cache, fetch)
    documents, metadata = _select(raw, source)
    if metadata != source["documents"]:
        raise ValueError("Selected passage IDs or checksums differ from the pinned manifest.")
    payload = b"".join(_json_bytes(document) for document in documents)
    manifest = {"schema": 1, "dataset": source["dataset"], "revision": source["revision"],
                "document_kind": "context passage", "selection": source["selection"],
                "source": source["source"], "license": source["license"],
                "attribution_sha256": source["attribution_sha256"],
                "documents_file": "documents.jsonl", "documents_sha256": sha256(payload),
                "documents": metadata,
                "totals": {"documents": len(documents), "words": sum(d["words"] for d in metadata),
                           "text_bytes": sum(d["bytes"] for d in metadata),
                           "chunks_160_words": sum(_chunk_count(d["text"]) for d in documents)}}
    # Write the completion manifest last, only after source selection is verified.
    _write(output / "documents.jsonl", payload)
    _write(output / "LICENSE", license_bytes)
    _write(output / "SOURCE.md", attribution)
    _write(output / "manifest.json", _json_bytes(manifest))
    load_documents(output)
    return manifest


def manifest_digest(path: Path) -> str:
    """Return the immutable manifest's SHA256 (accepts directory or manifest)."""
    path = Path(path)
    return sha256((path / "manifest.json" if path.is_dir() else path).read_bytes())


def load_documents(path: Path) -> list[dict]:
    """Read prepared passage documents only after all portable hashes agree."""
    path = Path(path)
    directory = path if path.is_dir() else path.parent
    if path.is_symlink() or any((directory / name).is_symlink() for name in FILES):
        raise ValueError("Prepared data files must not be symlinks.")
    manifest = _read_json(directory / "manifest.json")
    if manifest.get("schema") != 1 or manifest.get("documents_file") != "documents.jsonl":
        raise ValueError("Unsupported document manifest.")
    raw = (directory / "documents.jsonl").read_bytes()
    if sha256(raw) != manifest["documents_sha256"]:
        raise ValueError("Prepared document checksum changed.")
    if sha256((directory / "LICENSE").read_bytes()) != manifest["license"]["sha256"]:
        raise ValueError("Prepared license checksum changed.")
    if sha256((directory / "SOURCE.md").read_bytes()) != manifest["attribution_sha256"]:
        raise ValueError("Prepared attribution checksum changed.")
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Prepared document file is oversized.")
    try:
        documents = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid prepared document JSONL.") from exc
    expected = manifest["documents"]
    count = manifest["selection"]["count"]
    if len(documents) != count or len(expected) != count:
        raise ValueError("Prepared document count differs from the manifest.")
    ids, hashes, words, text_bytes, chunks = set(), set(), 0, 0, 0
    for document, item in zip(documents, expected):
        if set(document) != {"id", "title", "source_url", "text"} or not all(isinstance(v, str) for v in document.values()):
            raise ValueError("Invalid prepared document fields.")
        text = document["text"]
        normalized = sha256(" ".join(text.split()).encode("utf-8"))
        if document["id"] in ids or normalized in hashes:
            raise ValueError("Prepared documents contain duplicate IDs or passage texts.")
        ids.add(document["id"]); hashes.add(normalized)
        if any(document[key] != item[key] for key in ("id", "title", "source_url")):
            raise ValueError("Prepared document source metadata changed.")
        if (sha256(text.encode("utf-8")) != item["text_sha256"] or normalized != item["normalized_text_sha256"]
                or len(text.split()) != item["words"] or len(text.encode("utf-8")) != item["bytes"]
                or item["words"] < manifest["selection"]["minimum_words"]):
            raise ValueError("Prepared passage checksum/length differs from its manifest.")
        url = manifest["source"]["view_url"] + f"#L{item['source_line']}"
        if (document["source_url"] != url or not url.startswith("https://")
                or document["id"] != f"dolly-context-L{item['source_line']:05d}"):
            raise ValueError("Prepared document ID/source line changed.")
        words += item["words"]; text_bytes += item["bytes"]; chunks += _chunk_count(text)
    if manifest["totals"] != {"documents": count, "words": words, "text_bytes": text_bytes, "chunks_160_words": chunks}:
        raise ValueError("Prepared corpus totals differ from the manifest.")
    return documents
