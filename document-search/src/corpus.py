"""Download and verify the pinned Python documentation corpus without executing it."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE_BYTES = 60 * 1024 * 1024
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_rst(text: str) -> str:
    """Remove presentation markup while retaining prose, API names and code."""
    text = re.sub(r"(?m)^\s*\.\. _[^\n]+:\s*$", "", text)
    text = re.sub(r"(?m)^\s*[=~`^*+#-]{3,}\s*$", "", text)
    text = re.sub(r":[a-zA-Z][\w:]*:`([^`]+)`", r"\1", text)
    text = re.sub(r"`([^`<>]+)\s*<[^`>]+>`_?", r"\1", text)
    text = re.sub(r"(?m)^\s*\.\. (?:include|image|figure|index|seealso|toctree)::[^\n]*", "", text)
    text = re.sub(r"(?m)^\s*\.\. ([\w:]+)::\s*", r"\1 ", text)
    text = re.sub(r"(?m)^\s*:[\w-]+:\s*$", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def archive_members(data: bytes, names: set[str], archive_type: str) -> dict[str, bytes]:
    result = {}
    if archive_type == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len({item.filename for item in entries}) != len(entries):
                raise ValueError("Source archive has duplicate member names.")
            for item in entries:
                if item.filename in names:
                    if item.is_dir() or item.file_size > MAX_DOCUMENT_BYTES:
                        raise ValueError("Selected source member is not a bounded document.")
                    result[item.filename] = archive.read(item)
    elif archive_type == "tar.gz":
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            seen = set()
            for item in archive:
                if item.name not in names:
                    continue
                if item.name in seen or not item.isfile() or item.size > MAX_DOCUMENT_BYTES:
                    raise ValueError("Selected source member is duplicate, unsafe or oversized.")
                seen.add(item.name)
                stream = archive.extractfile(item)
                if stream is None:
                    raise ValueError("Source document could not be read.")
                result[item.name] = stream.read(MAX_DOCUMENT_BYTES + 1)
    else:
        raise ValueError("Unsupported source archive type.")
    if set(result) != names:
        raise ValueError("The archive does not contain every pinned corpus member.")
    return result


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def prepare(output: Path, cache: Path, *, source_path: Path = ROOT / "data/source.json", fetch=None) -> dict:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if output.is_symlink():
        raise ValueError("Choose a real corpus directory rather than a symlink.")
    documents = source["documents"]
    paths = [item["path"] for item in documents]
    if len(set(paths)) != len(paths):
        raise ValueError("Corpus destination paths are not unique.")
    for relative in paths:
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or str(path) != relative:
            raise ValueError("Unsafe corpus destination path.")
    if output.exists():
        unknown = [p.relative_to(output).as_posix() for p in output.rglob("*")
                   if p.is_file() and p.suffix in {".txt", ".md"}
                   and p.relative_to(output).as_posix() not in paths]
        if unknown:
            raise ValueError("Destination contains other documents; choose a new --output-dir.")
    cache.mkdir(parents=True, exist_ok=True)
    archive_path = cache / (source["archive"]["sha256"] + ".archive")
    data = archive_path.read_bytes() if archive_path.is_file() else b""
    if sha256(data) != source["archive"]["sha256"]:
        if fetch is None:
            request = urllib.request.Request(source["archive"]["url"], headers={"User-Agent": "nebius-serverless-cookbook"})
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read(MAX_ARCHIVE_BYTES + 1)
        else:
            data = fetch(source["archive"]["url"])
        if (len(data) > MAX_ARCHIVE_BYTES or len(data) != source["archive"]["bytes"]
                or sha256(data) != source["archive"]["sha256"]):
            raise ValueError("Source archive size/checksum differs from the pinned release.")
        write_bytes(archive_path, data)
    names = {item["member"] for item in documents} | {source["license"]["member"]}
    if source.get("queries_source"):
        names.add(source["queries_source"]["member"])
    members = archive_members(data, names, source["archive"]["type"])
    if sha256(members[source["license"]["member"]]) != source["license"]["sha256"]:
        raise ValueError("Source license differs from the pinned release.")
    if source.get("queries_source") and sha256(members[source["queries_source"]["member"]]) != source["queries_source"]["sha256"]:
        raise ValueError("Source FAQ differs from the pinned release.")
    prepared = []
    for item in documents:
        destination = output / item["path"]
        parent = output
        for part in PurePosixPath(item["path"]).parent.parts:
            parent = parent / part
            if parent.is_symlink():
                raise ValueError("Corpus destination has a symlinked parent directory.")
        raw = members[item["member"]]
        if sha256(raw) != item["sha256"]:
            raise ValueError("Source document checksum differs from its manifest.")
        text = raw.decode("utf-8")
        transformed = clean_rst(text) if source["archive"].get("format") == "rst" else text.strip() + "\n"
        payload = transformed.encode("utf-8")
        write_bytes(destination, payload)
        prepared.append({"path": item["path"], "sha256": sha256(payload), "source_sha256": item["sha256"],
                         "source_url": item["url"], "title": item["title"]})
    write_bytes(output / "DATA_LICENSE", members[source["license"]["member"]])
    manifest = {"schema": 1, "dataset": source["dataset"], "version": source["version"],
                "archive_sha256": source["archive"]["sha256"], "archive_url": source["archive"]["url"],
                "license": source["license"]["name"], "documents": prepared}
    if source.get("source_commit"):
        manifest["source_commit"] = source["source_commit"]
    write_bytes(output / ".corpus.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return manifest
