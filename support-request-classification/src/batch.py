#!/usr/bin/env python3
"""Run offline batched classification, retaining completed batches outside the GPU VM."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from artifacts import (digest_json, ensure_contract, load_batches, publish_attempt,
                       publish_batch, publish_bundle, read_attempts)
from baseline import predict as baseline_predict
from dataset import load_csv, load_dataset
from report import export_results
from prompting import messages_for, select_examples


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def log(event, **values):
    print(json.dumps({"event": event, **values}, sort_keys=True), flush=True)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")




class GpuSamples:
    """Optional point samples; not billed duration or an energy measurement."""
    def __init__(self):
        self.phase, self.values = "model_loading", []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        while not self.stop_event.is_set():
            try:
                p = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                                    "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=5)
                if p.returncode == 0:
                    util, memory = map(float, p.stdout.strip().splitlines()[0].split(","))
                    self.values.append({"at": utc_now(), "phase": self.phase,
                                        "utilization_percent": util, "memory_used_mib": memory})
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                pass
            self.stop_event.wait(3)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop_event.set()
        self.thread.join(timeout=6)


class VllmEngine:
    def __init__(self, config, labels):
        from vllm import LLM, SamplingParams
        from vllm.sampling_params import StructuredOutputsParams
        self.config, self.labels = config, labels
        self.examples = config.get("prompt_examples", [])
        self.llm = LLM(
            model=config["model"], revision=config["model_revision"],
            tokenizer_revision=config["model_revision"], trust_remote_code=False,
            dtype="bfloat16", max_model_len=config["max_model_len"],
            max_num_seqs=config["max_num_seqs"],
            gpu_memory_utilization=config["gpu_memory_utilization"],
            seed=config["seed"], enable_prefix_caching=True)
        self.params = SamplingParams(
            temperature=config["temperature"], max_tokens=config["max_tokens"],
            seed=config["seed"], structured_outputs=StructuredOutputsParams(choice=labels))

    def generate(self, rows):
        conversations = [messages_for(row, self.labels, self.examples) for row in rows]
        tokenizer = self.llm.get_tokenizer()
        for row, conversation in zip(rows, conversations):
            tokens = tokenizer.apply_chat_template(conversation, tokenize=True, add_generation_prompt=True)
            if len(tokens) + self.config["max_tokens"] > self.config["max_model_len"]:
                raise ValueError(f"Request {row['id']} exceeds the context limit; shorten it first.")
        outputs = self.llm.chat(conversations, sampling_params=self.params, use_tqdm=False)
        if len(outputs) != len(rows):
            raise ValueError("The model returned a different number of outputs than inputs.")
        records = []
        for row, output in zip(rows, outputs):
            answer = output.outputs[0]
            prediction, truncated = answer.text.strip(), answer.finish_reason == "length"
            records.append({**row, "response": answer.text, "predicted": prediction,
                            "valid": prediction in self.labels and not truncated,
                            "truncated": truncated,
                            "input_tokens": len(output.prompt_token_ids or []),
                            "output_tokens": len(answer.token_ids)})
        return records


def run(config, artifact_dir, *, limit=0, stop_after_batches=0, input_file=None,
        recipe_hash="local", work_dir=Path("/workspace/batch-results"), engine_factory=VllmEngine):
    started, started_at = time.monotonic(), utc_now()
    if limit < 0 or stop_after_batches < 0 or not 1 <= config["batch_size"] <= 512:
        raise ValueError("Limits must be nonnegative and batch_size must be 1–512.")
    work_dir.mkdir(parents=True, exist_ok=True)
    rows, labels, provenance, train_rows = load_dataset(
        work_dir / "dataset-cache", limit=0 if input_file is not None else limit, seed=config["seed"])
    if input_file is not None:
        rows = load_csv(input_file, labels)
        if limit:
            rows = rows[:limit]
        provenance = {**provenance, "input": "user_csv", "input_filename": input_file.name,
                      "input_sha256": digest_json(rows), "selected_rows": len(rows)}
    if not rows:
        raise ValueError("The input contains no requests.")
    examples = select_examples(train_rows, labels, config.get("examples_per_intent", 1))
    batches = [rows[i:i + config["batch_size"]] for i in range(0, len(rows), config["batch_size"])]
    partitions = [[r["id"] for r in batch] for batch in batches]
    contract = {"schema": 1, "config": config, "recipe_hash": recipe_hash,
                "input_sha256": digest_json(rows), "dataset": provenance, "labels": labels,
                "partitions": partitions, "prompt_examples": examples,
                "system_prompt": messages_for(rows[0], labels, examples)[0]["content"]}
    contract_hash = ensure_contract(artifact_dir, contract)
    saved = load_batches(artifact_dir, contract_hash, partitions)
    by_id = {r["id"]: r for r in rows}
    for batch in saved.values():
        for record in batch["records"]:
            original = by_id.get(record["id"])
            if not original or any(record.get(k) != original[k] for k in ("prompt", "expected")):
                raise ValueError("Saved output does not match the input.")
    reused_batches, reused_rows = len(saved), sum(len(b["records"]) for b in saved.values())
    attempt_id = "attempt-" + uuid.uuid4().hex[:12]
    log("input_ready", rows=len(rows), labels=len(labels), total_batches=len(batches),
        reused_batches=reused_batches, reused_rows=reused_rows, contract_hash=contract_hash)
    baseline_started = time.monotonic()
    baseline_predictions = baseline_predict(train_rows, rows, labels)
    baseline_seconds = time.monotonic() - baseline_started
    model_load_seconds, generation_seconds, new_batches, samples = 0.0, 0.0, 0, []
    pending = [i for i in range(len(batches)) if i not in saved]
    if pending:
        with GpuSamples() as sampler:
            load_started = time.monotonic()
            engine = engine_factory({**config, "prompt_examples": examples}, labels)
            model_load_seconds = time.monotonic() - load_started
            log("model_ready", model=config["model"], model_load_seconds=model_load_seconds)
            sampler.phase = "inference"
            for index in pending:
                batch_started = time.monotonic()
                records = engine.generate(batches[index])
                if len(records) != len(batches[index]) or [r["id"] for r in records] != partitions[index]:
                    raise ValueError("Output IDs differ from this batch's input order.")
                elapsed = time.monotonic() - batch_started
                generation_seconds += elapsed
                for record in records:
                    record["batch_id"] = index
                published = publish_batch(artifact_dir, contract_hash, index, records, partitions[index],
                                          {"attempt_id": attempt_id, "generation_seconds": elapsed})
                saved[index] = {"records": records, "manifest": {"stats": {"generation_seconds": elapsed}}}
                new_batches += 1
                log("batch_saved", index=index, rows=len(records), generation_seconds=elapsed,
                    completed_rows=sum(len(b["records"]) for b in saved.values()), path=str(published))
                if stop_after_batches and new_batches >= stop_after_batches:
                    break
            samples = sampler.values
    records_by_id = {r["id"]: r for index in sorted(saved) for r in saved[index]["records"]}
    records = [records_by_id[r["id"]] for r in rows if r["id"] in records_by_id]
    complete = len(records) == len(rows)
    attempt = {"attempt_id": attempt_id, "started_at": started_at, "ended_at": utc_now(),
               "worker_seconds": time.monotonic() - started, "model_load_seconds": model_load_seconds,
               "generation_seconds": generation_seconds, "baseline_seconds": baseline_seconds,
               "new_batches": new_batches, "new_rows": len(records) - reused_rows,
               "reused_batches": reused_batches, "reused_rows": reused_rows,
               "completed": complete, "gpu_samples": samples}
    publish_attempt(artifact_dir, attempt_id, attempt)
    attempts = read_attempts(artifact_dir)
    output = work_dir / attempt_id
    output.mkdir()
    with (output / "input.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "prompt", "expected"])
        writer.writeheader()
        writer.writerows(rows)
    retained_seconds = sum(b["manifest"].get("stats", {}).get("generation_seconds", 0) for b in saved.values())
    metadata = {"model": config["model"], "model_revision": config["model_revision"],
                "image": config["image"], "dataset": provenance, "contract_hash": contract_hash,
                "attempts": attempts, "completed": len(records), "total": len(rows),
                "baseline_predictions": baseline_predictions, "labels": labels,
                "prompting": {"mode": "few-shot" if examples else "zero-shot",
                              "examples_per_intent": config.get("examples_per_intent", 1),
                              "total_examples": len(examples), "source_split": "train",
                              "example_ids": [e["id"] for e in examples]},
                "timing": {"worker_seconds_all_completed_attempts": sum(a["worker_seconds"] for a in attempts),
                           "generation_seconds_all_completed_attempts": sum(a["generation_seconds"] for a in attempts),
                           "retained_batch_generation_seconds": retained_seconds,
                           "retained_rows_per_generation_second": len(records) / retained_seconds if retained_seconds else None,
                           "note": "Processing timers exclude provisioning, image pull and export. Retained-batch throughput excludes startup and discarded work; it is not billed GPU duration."},
                "cost": {"measured_billed_cost": None,
                         "note": "No invoice or savings claim is inferred from inference time or the hourly quote."}}
    logo = Path(__file__).with_name("nebius-logo.svg")
    if not logo.exists():
        logo = Path(__file__).resolve().parents[1] / "docs/brand/nebius-logo.svg"
    summary = export_results(output, rows, records, metadata, logo)
    for name, value in {"run_contract.json": contract, "attempts.json": attempts,
                        "config.json": config, "dataset_provenance.json": provenance}.items():
        write_json(output / name, value)
    versions = {"python": sys.version.split()[0]}
    for module in ("vllm", "torch", "transformers"):
        try:
            versions[module] = importlib.metadata.version(module)
        except importlib.metadata.PackageNotFoundError:
            pass
    write_json(output / "runtime.json", versions)
    recipe = Path(__file__).resolve().parents[1]
    for name, candidates in {
        "DATA_LICENSE": [Path(__file__).with_name("LICENSE"), recipe / "data/LICENSE", work_dir / "dataset-cache" / ("banking77-" + provenance["revision"]) / "LICENSE"],
        "DATA_SOURCE.md": [Path(__file__).with_name("SOURCE.md"), recipe / "data/SOURCE.md"],
    }.items():
        for candidate in candidates:
            if candidate.is_file():
                (output / name).write_bytes(candidate.read_bytes())
                break
    if not (output / "DATA_LICENSE").is_file() or not (output / "DATA_SOURCE.md").is_file():
        raise ValueError("Dataset attribution and license must be included in the exported result.")
    archive = work_dir / (attempt_id + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.iterdir()):
            if path.is_file():
                bundle.write(path, path.name)
    exported = publish_bundle(artifact_dir, archive, contract_hash, attempt_id)
    log("result_published", artifact=str(exported / "result.zip"), complete=complete,
        completed=len(records), total=len(rows), new_rows=attempt["new_rows"],
        reused_rows=reused_rows, attempt_id=attempt_id)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--artifact-dir", type=Path, required=True)
    p.add_argument("--recipe-hash", default="local")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--stop-after-batches", type=int, default=0)
    p.add_argument("--input-file", type=Path)
    p.add_argument("--work-dir", type=Path, default=Path("/workspace/batch-results"))
    a = p.parse_args()
    try:
        run(json.loads(a.config.read_text()), a.artifact_dir, limit=a.limit,
            stop_after_batches=a.stop_after_batches, input_file=a.input_file,
            recipe_hash=a.recipe_hash, work_dir=a.work_dir)
    except Exception as exc:
        log("failed", error=str(exc), note="Verified completed batches remain in Object Storage.")
        raise


if __name__ == "__main__":
    main()
