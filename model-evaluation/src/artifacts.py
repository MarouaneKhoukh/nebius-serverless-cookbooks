"""Immutable batch artifacts for a bucket mount, using data-only file writes.

A complete.json marker is always written last. Readers verify its size and
checksum before reusing an artifact; partial or corrupt publications are ignored.
One Job at a time may write a run directory. No cross-VM locking is attempted.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid
import zipfile


_DIGEST = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_BATCH = re.compile(r"batch-(\d{6,})-[0-9a-f]{32}")


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest_json(value) -> str:
    """Hash JSON with stable key ordering, UTF-8 and no non-finite numbers."""
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _digest(value: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError("A contract hash must be a lowercase SHA-256 digest")
    return value


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("Attempt IDs must be 1–64 filename-safe characters")
    return value


def _row_ids(value) -> list[str]:
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(set(value)) != len(value)):
        raise ValueError("Row IDs must be a nonempty list of unique nonempty strings")
    return value


def _index(value) -> int:
    if type(value) is not int or not 0 <= value < 1_000_000_000:
        raise ValueError("Batch index must be an integer from 0 to 999999999")
    return value


def _decode(data: bytes):
    def reject_constant(value):
        raise ValueError("Non-finite JSON number: " + value)
    return json.loads(data.decode("utf-8"), parse_constant=reject_constant)


def _write_json(path: Path, value) -> None:
    # Whole-file data writes only: bucket mounts do not provide POSIX rename.
    with path.open("wb") as stream:
        stream.write(_json_bytes(value) + b"\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _new_directory(parent: Path, name: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / name
    destination.mkdir(exist_ok=False)
    return destination


def _marker(kind: str, filename: str, size: int, checksum: str, **fields) -> dict:
    return {"schema": 1, "kind": kind, "file": filename, "bytes": size,
            "sha256": checksum,
            "published_at": datetime.now(timezone.utc).isoformat(), **fields}


def _directories(parent: Path) -> list[Path]:
    if not parent.exists():
        return []
    return sorted(path for path in parent.iterdir()
                  if path.is_dir() and not path.is_symlink())


def _read_marker(directory: Path, kind: str, filename: str) -> dict | None:
    path = directory / "complete.json"
    try:
        if path.is_symlink() or not path.is_file():
            return None
        marker = _decode(path.read_bytes())
        if (not isinstance(marker, dict) or marker.get("schema") != 1
                or marker.get("kind") != kind or marker.get("file") != filename
                or type(marker.get("bytes")) is not int or marker["bytes"] < 0
                or not isinstance(marker.get("published_at"), str)):
            return None
        _digest(marker.get("sha256"))
        return marker
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _verified_file(directory: Path, marker: dict) -> Path | None:
    path = directory / marker["file"]
    try:
        if (path.is_symlink() or not path.is_file()
                or path.stat().st_size != marker["bytes"]
                or _sha256(path) != marker["sha256"]):
            return None
        return path
    except OSError:
        return None


def ensure_contract(root: Path, contract: dict) -> str:
    """Reuse an intact matching contract; refuse intact incompatible contracts.

    Contracts use unique publication directories, so interrupted first writes
    cannot wedge a run or overwrite its prior complete contract.
    """
    if not isinstance(contract, dict):
        raise ValueError("The run contract must be a JSON object")
    expected = digest_json(contract)
    found = False
    for directory in _directories(root / "contracts"):
        marker = _read_marker(directory, "contract", "contract.json")
        if marker is None:
            continue
        path = _verified_file(directory, marker)
        if path is None:
            continue
        try:
            previous = _decode(path.read_bytes())
            if not isinstance(previous, dict):
                continue
            actual = digest_json(previous)
            if marker.get("contract_hash") != actual:
                continue
        except (OSError, ValueError, TypeError):
            continue
        if actual != expected:
            raise ValueError("This run has a different completed contract; use a new run ID")
        found = True
    if not found:
        directory = _new_directory(root / "contracts", "contract-" + uuid.uuid4().hex)
        data = _json_bytes(contract) + b"\n"
        (directory / "contract.json").write_bytes(data)
        _write_json(directory / "complete.json", _marker(
            "contract", "contract.json", len(data), hashlib.sha256(data).hexdigest(),
            contract_hash=expected))
    return expected


def publish_batch(root: Path, contract_hash: str, index: int, records: list,
                  row_ids: list[str], stats: dict) -> Path:
    """Publish one immutable completed batch; return its publication directory."""
    _digest(contract_hash)
    _index(index)
    _row_ids(row_ids)
    if (not isinstance(records, list) or len(records) != len(row_ids)
            or any(not isinstance(record, dict) for record in records)
            or [record.get("id") for record in records] != row_ids):
        raise ValueError("Records must match the exact row ID order of this batch")
    if not isinstance(stats, dict):
        raise ValueError("Batch stats must be a JSON object")
    _json_bytes(stats)
    data = b"".join(_json_bytes(record) + b"\n" for record in records)
    directory = _new_directory(root / "batches", f"batch-{index:06d}-{uuid.uuid4().hex}")
    (directory / "records.jsonl").write_bytes(data)
    _write_json(directory / "complete.json", _marker(
        "batch", "records.jsonl", len(data), hashlib.sha256(data).hexdigest(),
        contract_hash=contract_hash, index=index, row_ids=row_ids, stats=stats))
    return directory


def load_batches(root: Path, contract_hash: str,
                 partitions: list[list[str]]) -> dict[int, dict]:
    """Return the newest valid publication of each fixed input partition.

    A completed batch marker naming another contract is a hard error. Incomplete
    or corrupt publications are ignored, with intact older copies still usable.
    """
    _digest(contract_hash)
    if not isinstance(partitions, list):
        raise ValueError("Partitions must be a list of row ID lists")
    seen = set()
    for partition in partitions:
        _row_ids(partition)
        if seen.intersection(partition):
            raise ValueError("Row IDs must be unique across partitions")
        seen.update(partition)
    batches, versions = {}, {}
    for directory in _directories(root / "batches"):
        match = _BATCH.fullmatch(directory.name)
        if match is None:
            continue
        marker = _read_marker(directory, "batch", "records.jsonl")
        if marker is None:
            continue
        try:
            _digest(marker.get("contract_hash"))
        except ValueError:
            continue
        if marker["contract_hash"] != contract_hash:
            raise ValueError("A completed batch belongs to a different contract; use a new run ID")
        try:
            index = _index(marker.get("index"))
            if (index >= len(partitions) or index != int(match.group(1))
                    or marker.get("row_ids") != partitions[index]
                    or not isinstance(marker.get("stats"), dict)):
                continue
            _row_ids(marker["row_ids"])
            path = _verified_file(directory, marker)
            if path is None:
                continue
            records = [_decode(line) for line in path.read_bytes().splitlines()]
            if (len(records) != len(partitions[index])
                    or any(not isinstance(record, dict) for record in records)
                    or [record.get("id") for record in records] != partitions[index]):
                continue
            version = marker["published_at"], directory.name
            if index not in versions or version > versions[index]:
                versions[index] = version
                batches[index] = {"records": records, "manifest": marker}
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return dict(sorted(batches.items()))


def publish_attempt(root: Path, attempt_id: str, summary: dict) -> Path:
    """Save an immutable attempt summary with a verified completion marker."""
    _identifier(attempt_id)
    if not isinstance(summary, dict):
        raise ValueError("Attempt summary must be a JSON object")
    data = _json_bytes(summary) + b"\n"
    directory = _new_directory(root / "attempts", attempt_id)
    (directory / "summary.json").write_bytes(data)
    _write_json(directory / "complete.json", _marker(
        "attempt", "summary.json", len(data), hashlib.sha256(data).hexdigest(),
        attempt_id=attempt_id))
    return directory


def read_attempts(root: Path) -> list[dict]:
    """Read only intact completed attempt summaries, ordered by publication."""
    results = []
    for directory in _directories(root / "attempts"):
        marker = _read_marker(directory, "attempt", "summary.json")
        if marker is None or marker.get("attempt_id") != directory.name:
            continue
        path = _verified_file(directory, marker)
        if path is None:
            continue
        try:
            summary = _decode(path.read_bytes())
            if isinstance(summary, dict):
                results.append((marker["published_at"], directory.name, summary))
        except (OSError, ValueError, TypeError):
            continue
    return [summary for _, _, summary in sorted(results, key=lambda item: item[:2])]


def publish_bundle(root: Path, local_zip: Path, contract_hash: str,
                   attempt_id: str) -> Path:
    """Copy a finalized local ZIP to a unique export and publish its marker last."""
    _digest(contract_hash)
    _identifier(attempt_id)
    if local_zip.is_symlink() or not local_zip.is_file():
        raise ValueError("The local result ZIP must be a regular file")
    try:
        with zipfile.ZipFile(local_zip) as archive:
            if archive.testzip() is not None:
                raise ValueError("The local result ZIP has a corrupt member")
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("The local result ZIP is incomplete or invalid") from exc
    size, checksum = local_zip.stat().st_size, _sha256(local_zip)
    directory = _new_directory(root / "exports", attempt_id)
    target = directory / "result.zip"
    # copyfileobj copies bytes without chmod, timestamps, rename or other metadata.
    with local_zip.open("rb") as source, target.open("wb") as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)
    if target.stat().st_size != size or _sha256(target) != checksum:
        raise OSError("Result ZIP verification failed; no export completion marker was written")
    _write_json(directory / "complete.json", _marker(
        "bundle", "result.zip", size, checksum,
        contract_hash=contract_hash, attempt_id=attempt_id))
    return directory
