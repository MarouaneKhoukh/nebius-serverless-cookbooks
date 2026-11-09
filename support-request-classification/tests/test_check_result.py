"""Validate real worker-shaped exports with a CPU engine and fixture inputs."""

from copy import deepcopy
import csv
from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import batch as worker
from artifacts import digest_json

spec = importlib.util.spec_from_file_location("check_batch_result", ROOT / "scripts/check_result.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class NoGpuSamples:
    def __init__(self):
        self.phase, self.values = "test", []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class FixtureEngine:
    def __init__(self, _config, labels):
        self.labels = labels

    def generate(self, rows):
        return [{**row, "response": "billing" if row["prompt"].startswith("Refund") else "account",
                 "predicted": "billing" if row["prompt"].startswith("Refund") else "account",
                 "valid": True, "truncated": False, "input_tokens": 12, "output_tokens": 1}
                for row in rows]


class ResultCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.rows = [{"id": f"fixture-{i}", "prompt": f"Refund request {i}" if i % 2 == 0 else f"Reset password {i}",
                      "expected": "billing" if i % 2 == 0 else "account"} for i in range(5)]
        self.train = [{"id": "train-refund", "prompt": "Refund payment", "expected": "billing"},
                      {"id": "train-access", "prompt": "Reset password", "expected": "account"}]
        self.config = json.loads((ROOT / "config/job.json").read_text())
        self.config["batch_size"] = 2
        self.bucket = self.directory / "simulated-bucket/run"
        provenance = {"dataset": "CPU fixture, not a measured model run", "revision": "test-only",
                      "selection": {"limit": 0, "seed": 42}, "selected_rows": len(self.rows),
                      "source_files": {"LICENSE": {"sha256": hashlib.sha256((ROOT / "data/LICENSE").read_bytes()).hexdigest()}}}
        with patch.object(worker, "load_dataset", return_value=(deepcopy(self.rows), ["billing", "account"], provenance, deepcopy(self.train))), patch.object(worker, "GpuSamples", NoGpuSamples), redirect_stdout(io.StringIO()):
            partial = worker.run(self.config, self.bucket, stop_after_batches=1,
                                 work_dir=self.directory / "first-vm", recipe_hash="fixture-payload",
                                 engine_factory=FixtureEngine)
            self.partial_files = self.export_files(partial)
            shutil.rmtree(self.directory / "first-vm")
            complete = worker.run(self.config, self.bucket,
                                  work_dir=self.directory / "replacement-vm", recipe_hash="fixture-payload",
                                  engine_factory=FixtureEngine)
            self.files = self.export_files(complete)

    def export_files(self, summary):
        attempt_id = summary["attempts"][-1]["attempt_id"]
        with zipfile.ZipFile(self.bucket / "exports" / attempt_id / "result.zip") as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    @staticmethod
    def document(files, name):
        return json.loads(files[name])

    @staticmethod
    def set_document(files, name, value):
        files[name] = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()

    @staticmethod
    def csv_rows(files, name):
        return list(csv.DictReader(io.StringIO(files[name].decode(), newline="")))

    @staticmethod
    def set_rows(files, name, rows):
        fields = next(csv.reader(io.StringIO(files[name].decode())))
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        files[name] = stream.getvalue().encode()

    def write_zip(self, files, *, extras=None):
        path = self.directory / "result.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
            for name, content in extras or []:
                archive.writestr(name, content)
        return path

    def run_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["check_result.py", *map(str, arguments)]), redirect_stdout(stdout), redirect_stderr(stderr):
            checker.main()
        return stdout.getvalue()

    def test_fresh_worker_export_passes_with_observable_resume_evidence(self):
        result = checker.validate(self.files, require_resume=True)
        self.assertEqual((result["completed"], result["total"], result["reused_rows"]), (5, 5, 2))
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["contract_hash"], self.document(self.files, "summary.json")["contract_hash"])
        self.assertGreater(len(self.files["DATA_LICENSE"]), 10000)
        self.assertIn(b"BANKING77", self.files["DATA_SOURCE.md"])

    def test_zip_verifies_before_extracting_into_new_directory(self):
        archive = self.write_zip(self.files)
        output = self.directory / "verified"
        text = self.run_cli(archive, "--require-resume", "--output", output)
        self.assertIn('"completed": 5', text)
        self.assertEqual({path.name for path in output.iterdir()}, set(self.files))
        for name, data in self.files.items():
            self.assertEqual((output / name).read_bytes(), data)
        self.assertEqual(checker.validate({path.name: path.read_bytes() for path in output.iterdir()})["total"], 5)

    def test_unpacked_worker_export_is_supported(self):
        output = self.directory / "unpacked"
        output.mkdir()
        for name, data in self.files.items():
            (output / name).write_bytes(data)
        self.assertIn('"total": 5', self.run_cli(output, "--require-resume"))

    def test_changed_contract_or_input_is_refused(self):
        for name in ("run_contract.json", "input.csv"):
            files = dict(self.files)
            if name.endswith(".json"):
                value = self.document(files, name)
                value["config"]["model_revision"] = "different-revision"
                self.set_document(files, name, value)
            else:
                rows = self.csv_rows(files, name)
                rows[0]["prompt"] = "This is different input"
                self.set_rows(files, name, rows)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "checksum"):
                checker.validate(files)

    def test_predictions_cannot_be_joined_to_another_prompt_or_gold_label(self):
        for field in ("prompt", "expected"):
            files = dict(self.files)
            rows = self.csv_rows(files, "predictions.csv")
            rows[0][field] = "different input value"
            self.set_rows(files, "predictions.csv", rows)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "joined"):
                checker.validate(files)

    def test_duplicate_unknown_and_reordered_prediction_ids_are_refused(self):
        for mode in ("duplicate", "unknown", "reordered"):
            files = dict(self.files)
            rows = self.csv_rows(files, "predictions.csv")
            if mode == "duplicate":
                rows[0]["id"] = rows[1]["id"]
            elif mode == "unknown":
                rows[0]["id"] = "not-an-input"
            else:
                rows = rows[::-1]
            self.set_rows(files, "predictions.csv", rows)
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "IDs|order"):
                checker.validate(files)

    def test_missing_attribution_or_license_is_refused(self):
        for name in ("DATA_LICENSE", "DATA_SOURCE.md"):
            files = dict(self.files)
            del files[name]
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Missing result files"):
                checker.validate(files)

    def test_partial_run_requires_explicit_inspection_permission(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            checker.validate(self.partial_files)
        result = checker.validate(self.partial_files, allow_partial=True)
        self.assertEqual((result["completed"], result["total"]), (2, 5))
        with self.assertRaisesRegex(ValueError, "reused"):
            checker.validate(self.partial_files, allow_partial=True, require_resume=True)

    def test_missing_or_inconsistent_attempt_evidence_is_refused(self):
        for mode in ("empty", "mismatch", "no-reuse"):
            files = dict(self.files)
            attempts = self.document(files, "attempts.json")
            summary = self.document(files, "summary.json")
            if mode == "empty":
                attempts = []
                summary["attempts"] = attempts
            elif mode == "mismatch":
                attempts[0]["new_rows"] += 1
            else:
                for attempt in attempts:
                    attempt["reused_rows"] = 0
                summary["attempts"] = attempts
            self.set_document(files, "attempts.json", attempts)
            self.set_document(files, "summary.json", summary)
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "evidence|reused"):
                checker.validate(files, require_resume=True)

    def test_counts_and_model_config_must_match_export(self):
        for mode in ("completed", "remaining", "config"):
            files = dict(self.files)
            if mode == "config":
                value = self.document(files, "config.json")
                value["model"] = "some-other-model"
                self.set_document(files, "config.json", value)
            else:
                value = self.document(files, "summary.json")
                value[mode] += 1
                self.set_document(files, "summary.json", value)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                checker.validate(files)

    def test_traversal_and_duplicate_zip_members_are_refused_before_output(self):
        cases = [("../escape.txt", b"unsafe"), ("/absolute.txt", b"unsafe"), ("nested/file.txt", b"unsafe"), ("summary.json", b"duplicate")]
        for name, data in cases:
            with self.subTest(name=name):
                with patch("warnings.warn"):
                    archive = self.write_zip(self.files, extras=[(name, data)])
                output = self.directory / "should-not-exist"
                with self.assertRaises(SystemExit) as error:
                    self.run_cli(archive, "--output", output)
                self.assertEqual(error.exception.code, 1)
                self.assertFalse(output.exists())
                self.assertFalse((self.directory / "escape.txt").exists())

    def test_invalid_bundle_and_existing_results_are_preserved(self):
        files = dict(self.files)
        del files["input.csv"]
        archive = self.write_zip(files)
        output = self.directory / "untouched"
        with self.assertRaises(SystemExit):
            self.run_cli(archive, "--output", output)
        self.assertFalse(output.exists())
        archive = self.write_zip(self.files)
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("previous results")
        with self.assertRaises(SystemExit):
            self.run_cli(archive, "--output", output)
        self.assertEqual(marker.read_text(), "previous results")
        self.assertEqual(list(output.iterdir()), [marker])

    def test_dataset_provenance_must_match_the_hashed_contract(self):
        files = dict(self.files)
        provenance = self.document(files, "dataset_provenance.json")
        provenance["revision"] = "different-source-revision"
        self.set_document(files, "dataset_provenance.json", provenance)
        with self.assertRaisesRegex(ValueError, "provenance|dataset|contract"):
            checker.validate(files)

    def test_empty_attribution_files_do_not_count_as_preserved_credit(self):
        for name in ("DATA_LICENSE", "DATA_SOURCE.md"):
            files = dict(self.files)
            files[name] = b""
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "license|attribution|source|credit"):
                checker.validate(files)


if __name__ == "__main__":
    unittest.main()
