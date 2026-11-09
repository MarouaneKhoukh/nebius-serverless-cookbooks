"""Pinned BANKING77 input and user CSV validation; no model or cloud credentials."""

from __future__ import annotations

import collections
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import tempfile
import urllib.error
import urllib.request

REVISION = "57ec275d8078af65b7731c2a98be812d844a6d6b"
BASE_URL = f"https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/{REVISION}/"
SOURCE_FILES = {
    "train.csv": {"path": "banking_data/train.csv", "sha256": "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b", "bytes": 839073, "rows": 10003},
    "test.csv": {"path": "banking_data/test.csv", "sha256": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d", "bytes": 239961, "rows": 3080},
    "categories.json": {"path": "banking_data/categories.json", "sha256": "53261da888122daf2d120d925458631d9619e15d82e56052e7a42e535ce32b63", "bytes": 2036, "rows": 77},
    "LICENSE": {"path": "LICENSE", "sha256": "7e7170e3cebf88a9f60c7b8421418323c09304da1af4d5e90f4da1dc1c8a2661", "bytes": 18650},
}
MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_ROWS = 100000
MAX_ID_CHARS = 200
MAX_PROMPT_CHARS = 20000


class DatasetError(ValueError):
    """A dataset or input error safe to display to the reader."""


def source_manifest() -> dict:
    """Return fresh metadata so callers cannot mutate the source constants."""
    return {
        "dataset": "BANKING77",
        "publisher": "PolyAI",
        "revision": REVISION,
        "repository": "https://github.com/PolyAI-LDN/task-specific-datasets",
        "paper": "https://aclanthology.org/2020.nlp4convai-1.5/",
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_schema": ["text", "category"],
        "source_files": {name: {**spec, "url": BASE_URL + spec["path"]} for name, spec in SOURCE_FILES.items()},
    }


def _check_bytes(data: bytes, spec: dict, name: str) -> None:
    if len(data) != spec["bytes"] or hashlib.sha256(data).hexdigest() != spec["sha256"]:
        raise DatasetError(f"Source verification failed for {name}; expected the pinned size and SHA-256. Remove that cached file and retry.")


def _source_bytes(cache: Path, name: str) -> bytes:
    # Only fixed manifest names become paths; HTTP headers/redirects cannot choose filenames.
    if Path(name).name != name or name not in SOURCE_FILES:
        raise DatasetError("Unknown source file")
    spec = SOURCE_FILES[name]
    path = cache / name
    if path.is_symlink():
        raise DatasetError(f"Refusing a symlink in the dataset cache: {name}")
    if path.exists():
        if not path.is_file():
            raise DatasetError(f"Dataset cache entry is not a regular file: {name}")
        if path.stat().st_size != spec["bytes"]:
            raise DatasetError(f"Source verification failed for {name}; remove that cached file and retry.")
        data = path.read_bytes()
        _check_bytes(data, spec, name)
        return data
    temporary = None
    try:
        request = urllib.request.Request(BASE_URL + spec["path"], headers={"User-Agent": "nebius-serverless-cookbook/1"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(spec["bytes"] + 1)
        _check_bytes(data, spec, name)
        with tempfile.NamedTemporaryFile("wb", dir=cache, prefix=".banking77-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        return data
    except (OSError, urllib.error.URLError) as exc:
        raise DatasetError(f"Cannot download/cache {name}. Check network access and the cache directory.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _upstream_rows(data: bytes, split: str, labels: list[str]) -> list[dict[str, str]]:
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""), strict=True)
        if reader.fieldnames != ["text", "category"]:
            raise DatasetError(f"Unexpected upstream {split} columns")
        rows = []
        for index, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()):
                raise DatasetError(f"Malformed upstream {split} row {index}")
            if not row["text"].strip() or row["category"] not in labels:
                raise DatasetError(f"Empty text or unknown category in upstream {split} row {index}")
            rows.append({"id": f"banking77-{split}-{index:06d}", "prompt": row["text"], "expected": row["category"]})
    except (UnicodeError, csv.Error) as exc:
        raise DatasetError(f"Cannot decode upstream {split} CSV") from exc
    if len(rows) != SOURCE_FILES[f"{split}.csv"]["rows"]:
        raise DatasetError(f"Unexpected upstream {split} row count")
    if {row["expected"] for row in rows} != set(labels):
        raise DatasetError(f"Upstream {split} does not cover the complete taxonomy")
    return rows


def load_dataset(cache_dir: Path, limit: int = 0, seed: int = 42) -> tuple[list[dict], list[str], dict, list[dict]]:
    """Return shuffled TEST rows, exact labels, provenance and separate TRAIN rows.

    IDs refer to original 1-based CSV records, before shuffling. A zero limit
    selects the full test split. Training rows stay separate for the CPU
    baseline and selected prompt contexts; test labels are never model input.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0 or limit > SOURCE_FILES["test.csv"]["rows"]:
        raise DatasetError(f"limit must be 0 (all rows) or 1–{SOURCE_FILES['test.csv']['rows']}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise DatasetError("seed must be an integer")
    cache_root = Path(cache_dir)
    if cache_root.is_symlink():
        raise DatasetError("Dataset cache directory must not be a symlink")
    cache = cache_root / f"banking77-{REVISION}"
    if cache.is_symlink():
        raise DatasetError("Dataset cache directory must not be a symlink")
    try:
        cache.mkdir(parents=True, exist_ok=True)
        raw = {name: _source_bytes(cache, name) for name in SOURCE_FILES}
        labels = json.loads(raw["categories.json"])
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatasetError("Cannot read the pinned dataset cache") from exc
    if not isinstance(labels, list) or len(labels) != SOURCE_FILES["categories.json"]["rows"] or any(not isinstance(label, str) or not label or label != label.strip() for label in labels) or len(set(labels)) != len(labels):
        raise DatasetError("The source taxonomy must contain unique nonempty labels in upstream order")
    rows = _upstream_rows(raw["test.csv"], "test", labels)
    counts = collections.Counter(row["expected"] for row in rows)
    if len(set(counts.values())) != 1:
        raise DatasetError("The pinned test split must have equal counts per intent")
    train_rows = _upstream_rows(raw["train.csv"], "train", labels)
    random.Random(seed).shuffle(rows)
    if limit:
        rows = rows[:limit]
    provenance = {
        **source_manifest(),
        "selection": {"split": "test", "seed": seed, "limit": limit, "method": "seeded shuffle of original test-row order, then prefix"},
        "selected_rows": len(rows),
        "test_rows": SOURCE_FILES["test.csv"]["rows"],
        "training_rows": len(train_rows),
        "input_sha256": hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }
    return rows, labels, provenance, train_rows


def load_csv(path: Path, labels: list[str]) -> list[dict[str, str]]:
    """Read custom id,prompt[,expected] CSV; blank expected means unlabelled."""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise DatasetError(f"Input CSV exceeds {MAX_INPUT_BYTES} bytes")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            fields = reader.fieldnames
            if not fields or not {"id", "prompt"}.issubset(fields) or len(fields) != len(set(fields)):
                raise DatasetError("CSV needs unique column names including id,prompt; expected is optional")
            rows, seen = [], set()
            for line, source in enumerate(reader, 2):
                if len(rows) >= MAX_ROWS:
                    raise DatasetError(f"Input CSV exceeds {MAX_ROWS} rows")
                if None in source or any(value is None for value in source.values()):
                    raise DatasetError(f"Malformed CSV row at line {line}")
                row = {"id": source["id"].strip(), "prompt": source["prompt"].strip(), "expected": source.get("expected", "").strip()}
                if not row["id"] or not row["prompt"]:
                    raise DatasetError(f"Empty id or prompt at line {line}")
                if len(row["id"]) > MAX_ID_CHARS or any(ord(char) < 32 for char in row["id"]):
                    raise DatasetError(f"ID at line {line} exceeds {MAX_ID_CHARS} characters or contains a control character")
                if len(row["prompt"]) > MAX_PROMPT_CHARS:
                    raise DatasetError(f"Prompt at line {line} exceeds {MAX_PROMPT_CHARS} characters")
                if row["id"] in seen:
                    raise DatasetError(f"Duplicate id at line {line}: {row['id']}")
                if row["expected"] and row["expected"] not in labels:
                    raise DatasetError(f"Unknown expected label at line {line}; preserve exact taxonomy spelling")
                seen.add(row["id"])
                rows.append(row)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise DatasetError("Cannot read input CSV; use a readable UTF-8 CSV with valid quoting") from exc
    if not rows:
        raise DatasetError("CSV has no input rows")
    return rows
