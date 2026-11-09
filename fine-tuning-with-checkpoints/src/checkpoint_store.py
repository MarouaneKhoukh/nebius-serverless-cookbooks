"""Publish complete training state to a bucket mount without POSIX metadata operations."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict | list) -> None:
    """A whole-file write, not append/rename/chmod, also works on the S3 mount."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as target:
        json.dump(value, target, indent=2, sort_keys=True)
        target.write("\n")


def ensure_contract(root: Path, contract: dict) -> None:
    path = root / "run_contract.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != contract:
            raise ValueError("This run directory belongs to different inputs/config. Use a new run ID.")
    else:
        write_json(path, contract)


def safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Unsafe checkpoint member: {value!r}")
    return path


def inspect_checkpoint(path: Path) -> tuple[int, list[Path]]:
    required = {"trainer_state.json", "optimizer.pt", "scheduler.pt", "rng_state.pth", "adapter_config.json"}
    files = sorted(item for item in path.rglob("*") if item.is_file())
    names = {item.relative_to(path).as_posix() for item in files}
    missing = required - names
    if not ({"adapter_model.safetensors", "adapter_model.bin"} & names):
        missing.add("adapter_model.safetensors (or .bin)")
    if missing:
        raise ValueError(f"Incomplete full training checkpoint: {sorted(missing)}")
    if any(item.is_symlink() for item in files):
        raise ValueError("Checkpoint symlinks are not supported")
    state = json.loads((path / "trainer_state.json").read_text(encoding="utf-8"))
    step = int(state["global_step"])
    if step < 1:
        raise ValueError("A recovery checkpoint must contain at least one optimizer step")
    return step, files


def publish_checkpoint(source: Path, root: Path, contract_hash: str) -> Path:
    step, files = inspect_checkpoint(source)
    destination = root / "checkpoints" / f"checkpoint-{step}-{uuid.uuid4().hex[:12]}"
    destination.mkdir(parents=True, exist_ok=False)
    members = []
    for file in files:
        relative = file.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
        members.append({"path": relative.as_posix(), "bytes": file.stat().st_size, "sha256": sha256(file)})
    # The marker is last. Interrupted copies without it are never resumed.
    write_json(destination / "complete.json", {
        "schema": 1, "global_step": step, "contract_hash": contract_hash, "files": members,
    })
    return destination


def verify_published(path: Path, contract_hash: str) -> dict:
    manifest = json.loads((path / "complete.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("contract_hash") != contract_hash:
        raise ValueError("Checkpoint contract does not match this run")
    if not manifest.get("files"):
        raise ValueError("Empty checkpoint manifest")
    for member in manifest["files"]:
        file = path / safe_relative(member["path"])
        if not file.is_file() or file.stat().st_size != member["bytes"] or sha256(file) != member["sha256"]:
            raise ValueError(f"Checkpoint member failed verification: {member['path']}")
    step, _ = inspect_checkpoint(path)
    if step != int(manifest["global_step"]):
        raise ValueError("Checkpoint step differs from its manifest")
    return manifest


def latest_checkpoint(root: Path, contract_hash: str) -> tuple[Path, dict] | None:
    parent = root / "checkpoints"
    if not parent.exists():
        return None
    candidates = []
    for path in parent.iterdir():
        match = re.fullmatch(r"checkpoint-(\d+)-[a-f0-9]+", path.name)
        if match and (path / "complete.json").is_file():
            candidates.append((int(match.group(1)), path))
    # A partial newest copy is ignored. If an older complete copy is corrupt,
    # verification also falls back to the next intact complete checkpoint.
    for _, path in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            return path, verify_published(path, contract_hash)
        except (ValueError, OSError, KeyError, json.JSONDecodeError):
            continue
    if candidates:
        raise ValueError("No verified complete checkpoint remains in this run")
    return None


def restore_checkpoint(published: Path, manifest: dict, local_root: Path) -> Path:
    destination = local_root / f"checkpoint-{manifest['global_step']}"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for member in manifest["files"]:
        relative = safe_relative(member["path"])
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(published / relative, target)
    return destination
