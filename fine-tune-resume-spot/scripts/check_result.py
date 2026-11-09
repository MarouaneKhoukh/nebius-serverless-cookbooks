"""Inspect a downloaded result ZIP without extracting files or loading the model."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def check(path: Path, require_resume: bool = False) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise ValueError("ZIP contains unsafe member paths")
        def read(name):
            return json.loads(archive.read(name))
        summary = read("summary.json")
        contract = read("run_contract.json")
        contract_hash = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
        proof = read("checkpoint-proof.json")
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
