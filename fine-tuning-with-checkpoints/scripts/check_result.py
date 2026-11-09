"""Inspect a downloaded result ZIP without extracting files or loading the model."""

import argparse
import csv
import io
import hashlib
import json
from pathlib import Path
import zipfile


def check(path: Path, require_resume: bool = False) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if len(names) != len(archive.namelist()) or sum(m.file_size for m in archive.infolist()) > 500 * 1024**2:
            raise ValueError("ZIP has duplicate members or exceeds the 500 MiB inspection limit")
        if archive.testzip() is not None:
            raise ValueError("ZIP checksum validation failed")
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise ValueError("ZIP contains unsafe member paths")
        def read(name):
            return json.loads(archive.read(name))
        summary = read("summary.json")
        contract = read("run_contract.json")
        contract_hash = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
        proof = read("checkpoint-proof.json")
        provenance = read("dataset_provenance.json")
        if provenance != contract.get("dataset"):
            raise ValueError("Dataset provenance differs from the run contract")
        for name, field in (("train.jsonl", "train_sha256"), ("test.csv", "test_sha256")):
            if hashlib.sha256(archive.read(name)).hexdigest() != contract[field]:
                raise ValueError("Prepared data differs from the run contract: " + name)
        if hashlib.sha256(archive.read("DATA_LICENSE")).hexdigest() != provenance["source_files"]["LICENSE"]["sha256"]:
            raise ValueError("The verified dataset license is missing or changed")
        if not archive.read("DATA_SOURCE.md").strip():
            raise ValueError("Dataset attribution is missing")
        examples = list(csv.DictReader(io.StringIO(archive.read("test.csv").decode("utf-8"))))
        training = [json.loads(line) for line in archive.read("train.jsonl").decode("utf-8").splitlines() if line.strip()]
        if (summary["test_examples"] != len(examples) or summary["train_examples"] != len(training)
                or [r["id"] for r in examples] != provenance["test_ids"]
                or [r["id"] for r in training] != provenance["train_ids"]):
            raise ValueError("Selected dataset counts or source IDs disagree")
        train_text = {r["messages"][1]["content"].strip().casefold() for r in training}
        if train_text & {r["prompt"].strip().casefold() for r in examples}:
            raise ValueError("Training and test text overlap")
        for name in ("before.json", "after.json") if summary["completed"] else ("before.json",):
            result = read(name)
            joined = [{k:r[k] for k in ("id","prompt","expected")} for r in result["predictions"]]
            if joined != examples or result["model_revision"] != contract["model_revision"]:
                raise ValueError("Evaluation predictions differ from the held-out input or model pin")
            if result["total"] != len(examples) or result["correct"] != sum(r["prediction"] == r["expected"] for r in result["predictions"]):
                raise ValueError("Evaluation score counts are inconsistent")
        if proof["contract_hash"] != contract_hash or summary["contract_hash"] != contract_hash:
            raise ValueError("Run contract and checkpoint proof do not match")
        if summary["global_step"] != proof["global_step"]:
            raise ValueError("Training summary and checkpoint proof disagree")
        required = {"optimizer.pt", "scheduler.pt", "rng_state.pth", "trainer_state.json", "adapter_config.json"}
        if not required.issubset({entry["path"] for entry in proof["files"]}):
            raise ValueError("Proof does not describe a full training checkpoint")
        if "report.html" not in names or b"Powered by Nebius Serverless AI" not in archive.read("report.html"):
            raise ValueError("Branded result report is missing")
        if summary["completed"]:
            if summary["global_step"] != summary["max_steps"]:
                raise ValueError("Final step does not equal the declared training schedule")
            if "adapter/adapter_config.json" not in names or not any(name.startswith("adapter/adapter_model.") for name in names):
                raise ValueError("Final adapter is missing")
            after = read("after.json")
            for result in (read("before.json"), after):
                if result["total"] != len(result["predictions"]) or result["correct"] != sum(row["correct"] for row in result["predictions"]):
                    raise ValueError("Scorecard counts disagree with per-example predictions")
        if require_resume:
            sessions = [read(name) for name in names if name.startswith("summary-") and name.endswith(".json")]
            if not summary["completed"] or not any(row["resumed_from_step"] > 0 for row in sessions):
                raise ValueError("No completed resumed session was recorded")
        return {"completed": summary["completed"], "global_step": summary["global_step"],
                "max_steps": summary["max_steps"], "resumed_from_step": summary["resumed_from_step"],
                "before_accuracy": read("before.json")["accuracy"],
                "after_accuracy": read("after.json")["accuracy"] if summary["completed"] else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path)
    parser.add_argument("--require-resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.zip, args.require_resume), indent=2))


if __name__ == "__main__":
    main()
