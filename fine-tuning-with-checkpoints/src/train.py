"""Run the existing Axolotl image with durable full-state checkpoints on Spot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

from checkpoint_store import (ensure_contract, latest_checkpoint, restore_checkpoint,
                              sha256, write_json)
from evaluate import LABELS, SYSTEM_PROMPT, evaluate, read_examples, render_report
from data_prep import prepare
from banking77 import REVISION


def defaults():
    source = Path(__file__).resolve().parent
    root = source.parent if (source.parent / "config").is_dir() else source
    return root


def bundle(source: Path, destination: Path, files: list[Path]) -> None:
    # ZIP is finalized on local disk before the whole file is copied to S3 FUSE.
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite an existing published bundle: {destination.name}")
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file():
                        archive.write(child, Path(path.name) / child.relative_to(path))
            elif path.is_file():
                archive.write(path, path.name)
    shutil.copyfile(source, destination)


def main() -> None:
    root = defaults()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=root / ("config/train.yaml" if (root / "config").is_dir() else "train.yaml"))
    parser.add_argument("--data-config", type=Path, default=root / ("config/data.json" if (root / "config").is_dir() else "data.json"))
    parser.add_argument("--logo", type=Path, default=root / ("docs/brand/nebius-logo.svg" if (root / "docs").is_dir() else "nebius-logo.svg"))
    parser.add_argument("--artifact-dir", type=Path, default=Path(os.environ.get("ARTIFACT_DIR", "/data/support-lora-demo")))
    parser.add_argument("--local-dir", type=Path, default=Path("/workspace/spot-cookbook"))
    parser.add_argument("--stop-after-step", type=int, default=int(os.environ.get("STOP_AFTER_STEP", "0")))
    args = parser.parse_args()
    import yaml

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if args.stop_after_step < 0 or (args.stop_after_step and (args.stop_after_step % cfg["save_steps"] or args.stop_after_step >= cfg["max_steps"])):
        raise ValueError("Controlled stop must be a positive save-step boundary below max_steps")
    if not args.logo.is_file():
        raise ValueError("The authentic Nebius logo must be included with the recipe")
    inputs = args.local_dir / "inputs"
    selection = json.loads(args.data_config.read_text())
    provenance = prepare(args.local_dir / "dataset-cache", inputs, selection)
    if json.loads((inputs / "categories.json").read_text()) != list(LABELS):
        raise ValueError("Prepared intent labels differ from the pinned taxonomy")
    args.train, args.test = inputs / "train.jsonl", inputs / "test.csv"
    print(json.dumps({"event":"data_ready", **provenance["selection"]}), flush=True)
    examples = read_examples(args.test)
    train_rows = [json.loads(line) for line in args.train.read_text().splitlines() if line.strip()]
    prompts = {row["messages"][1]["content"] for row in train_rows}
    if len(prompts) != len(train_rows) or prompts & {row["prompt"] for row in examples}:
        raise ValueError("Training prompts must be unique and separate from the held-out set")
    contract = {"schema": 1, "model": cfg["base_model"], "config_sha256": sha256(args.config),
                "train_sha256": sha256(args.train), "test_sha256": sha256(args.test),
                "system_prompt": SYSTEM_PROMPT, "dataset": provenance}
    existing_contract = args.artifact_dir / "run_contract.json"
    if existing_contract.exists():
        model_revision = json.loads(existing_contract.read_text())["model_revision"]
    else:
        model_revision = cfg["revision_of_model"]
    if model_revision != cfg["revision_of_model"]:
        raise ValueError("The saved model revision differs from the configured pin")
    contract["model_revision"] = model_revision
    contract_hash = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    ensure_contract(args.artifact_dir, contract)
    args.local_dir.mkdir(parents=True, exist_ok=True)
    output = args.local_dir / "training"
    output.mkdir(exist_ok=True)
    checkpoint = latest_checkpoint(args.artifact_dir, contract_hash)
    resumed_step = checkpoint[1]["global_step"] if checkpoint else 0
    result_path = args.artifact_dir / "result.zip"
    if result_path.exists():
        with zipfile.ZipFile(result_path) as existing:
            result_summary = json.loads(existing.read("summary.json"))
            if (result_summary["contract_hash"] != contract_hash or not result_summary["completed"]
                    or result_summary["global_step"] != cfg["max_steps"]
                    or "after.json" not in existing.namelist()):
                raise ValueError("Existing result.zip is not a complete result for this run. Use a new run ID.")
        print(json.dumps({"event": "already_complete", "global_step": resumed_step, "result": "result.zip"}), flush=True)
        return
    cfg["datasets"][0]["path"] = str(args.train.resolve())
    cfg["revision_of_model"] = model_revision
    cfg["output_dir"] = str(output)
    cfg["dataset_prepared_path"] = str(args.local_dir / "prepared")
    if checkpoint:
        cfg["resume_from_checkpoint"] = str(restore_checkpoint(checkpoint[0], checkpoint[1], args.local_dir / "restored"))
    runtime_config = args.local_dir / "train.yaml"
    runtime_config.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    before_path = args.artifact_dir / "before.json"
    before_valid = False
    if before_path.exists():
        try:
            previous = json.loads(before_path.read_text())
            before_valid = (previous["model_revision"] == model_revision and
                [r["id"] for r in previous["predictions"]] == [r["id"] for r in examples] and
                previous["total"] == len(examples))
        except (ValueError, KeyError, TypeError):
            pass
    if not before_valid:
        print(json.dumps({"event": "evaluating_base", "examples": len(examples)}), flush=True)
        write_json(before_path, evaluate(cfg["base_model"], examples, revision=model_revision))
    session = uuid.uuid4().hex[:12]
    environment = os.environ.copy()
    environment.update({"ARTIFACT_DIR": str(args.artifact_dir), "RUN_CONTRACT_HASH": contract_hash,
                        "RUN_SESSION": session, "STOP_AFTER_STEP": str(args.stop_after_step),
                        "TOKENIZERS_PARALLELISM": "false", "WANDB_DISABLED": "true"})
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parent) + os.pathsep + environment.get("PYTHONPATH", "")
    start = time.monotonic()
    print(json.dumps({"event": "starting_axolotl", "session": session, "resumed_from_step": resumed_step,
                      "stop_after_step": args.stop_after_step, "max_steps": cfg["max_steps"]}), flush=True)
    if resumed_step < cfg["max_steps"]:
        subprocess.run(["axolotl", "train", str(runtime_config)], env=environment, check=True)
    else:
        print(json.dumps({"event": "training_already_finished_exporting_checkpoint", "global_step": resumed_step}), flush=True)
    checkpoint = latest_checkpoint(args.artifact_dir, contract_hash)
    if checkpoint is None:
        raise RuntimeError("Axolotl returned without a verified durable full-state checkpoint")
    published, manifest = checkpoint
    global_step = manifest["global_step"]
    summary = {"schema": 1, "model": cfg["base_model"], "model_revision": model_revision, "session": session,
               "resumed_from_step": resumed_step, "global_step": global_step,
               "max_steps": cfg["max_steps"], "completed": global_step >= cfg["max_steps"],
               "controlled_stop": bool(args.stop_after_step), "training_wall_seconds": time.monotonic() - start,
               "checkpoint_directory": published.name,
               "contract_hash": contract_hash, "recovery_exercise": "separate Jobs with a controlled checkpoint stop"}
    summary.update({"dataset":"BANKING77", "train_examples":len(train_rows), "test_examples":len(examples),
                    "effective_batch_size":cfg["micro_batch_size"] * cfg["gradient_accumulation_steps"],
                    "trainer_epoch":json.loads((published / "trainer_state.json").read_text()).get("epoch"),
                    "dataset_selection":provenance["selection"]})
    summary["runtime_versions"] = {package: importlib.metadata.version(package) for package in ("axolotl", "torch", "transformers", "peft")}
    write_json(args.artifact_dir / f"summary-{session}.json", summary)
    stage = args.local_dir / f"result-{session}"
    stage.mkdir()
    write_json(stage / "summary.json", summary)
    write_json(stage / "checkpoint-proof.json", manifest)
    shutil.copyfile(runtime_config, stage / "train.yaml")
    shutil.copyfile(args.artifact_dir / "run_contract.json", stage / "run_contract.json")
    shutil.copyfile(published / "trainer_state.json", stage / "trainer_state.json")
    shutil.copyfile(before_path, stage / "before.json")
    shutil.copyfile(args.train, stage / "train.jsonl")
    shutil.copyfile(args.test, stage / "test.csv")
    shutil.copyfile(inputs / "provenance.json", stage / "dataset_provenance.json")
    license_path = args.local_dir / "dataset-cache" / ("banking77-" + REVISION) / "LICENSE"
    shutil.copyfile(license_path, stage / "DATA_LICENSE")
    source_path = root / ("data/SOURCE.md" if (root / "data").is_dir() else "SOURCE.md")
    shutil.copyfile(source_path, stage / "DATA_SOURCE.md")
    after_path = stage / "after.json"
    if summary["completed"]:
        adapter = stage / "adapter"
        adapter.mkdir(exist_ok=True)
        # The complete checkpoint also suffices if training finished in an earlier
        # Job that was interrupted before evaluation/export could finish.
        adapter_source = output if any(output.glob("adapter_model.*")) else published
        for file in adapter_source.iterdir():
            if file.is_file() and (file.name == "adapter_config.json" or file.name.startswith("adapter_model.")):
                shutil.copyfile(file, adapter / file.name)
        if not (adapter / "adapter_config.json").is_file() or not any(adapter.glob("adapter_model.*")):
            raise RuntimeError("Final adapter files are missing")
        write_json(after_path, evaluate(cfg["base_model"], examples, adapter, revision=model_revision))
    before = json.loads(before_path.read_text())
    after = json.loads(after_path.read_text()) if summary["completed"] else None
    report = stage / "report.html"
    report.write_text(render_report(before, after, summary, args.logo), encoding="utf-8")
    for name, result in (("before", before), ("after", after)):
        if result is None: continue
        with (stage / (name + "_predictions.csv")).open("w",newline="",encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,fieldnames=["id","prompt","expected","prediction","response","valid_label","correct"],extrasaction="ignore",lineterminator="\n")
            writer.writeheader();writer.writerows(result["predictions"])
    final_files = list(stage.iterdir())
    final_files.extend(args.artifact_dir.glob("summary-*.json"))
    final_files.extend(args.artifact_dir.glob("checkpoint-events-*.json"))
    recovery_name = None
    if summary["completed"]:
        bundle(args.local_dir / "result.zip", result_path, final_files)
    else:
        recovery_name = f"recovery-{session}.zip"
        bundle(args.local_dir / recovery_name, args.artifact_dir / recovery_name, [published, *final_files])
    print(json.dumps({"event": "recipe_finished", **summary,
                      "result": "result.zip" if summary["completed"] else None,
                      "recovery": recovery_name}), flush=True)


if __name__ == "__main__":
    main()
