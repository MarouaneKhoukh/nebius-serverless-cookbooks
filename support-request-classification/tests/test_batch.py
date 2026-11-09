"""CPU integration checks: fresh workers reuse verified completed batches."""

from copy import deepcopy
import csv
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import batch as worker
from artifacts import read_attempts


class NoGpuSamples:
    def __init__(self):
        self.phase = "test"
        self.values = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class FakeEngine:
    """Predict from prompt text only, retaining the actual input IDs for checks."""
    def __init__(self, config, labels):
        self.labels = labels
        self.calls = []

    def generate(self, rows):
        self.calls.append([row["id"] for row in rows])
        result = []
        for row in rows:
            predicted = "billing" if row["prompt"].startswith("Refund") else "account"
            result.append({**row, "response": predicted, "predicted": predicted,
                           "valid": predicted in self.labels, "truncated": False,
                           "input_tokens": 10, "output_tokens": 1})
        return result


class BatchIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.artifacts = self.directory / "bucket" / "run"
        self.labels = ["billing", "account"]
        self.rows = self.make_rows(7)
        self.train_rows = [
            {"id": "train-1", "prompt": "Refund the payment", "expected": "billing"},
            {"id": "train-2", "prompt": "Reset my password", "expected": "account"},
        ]
        recipe = Path(__file__).resolve().parents[1]
        self.config = json.loads((recipe / "config/job.json").read_text())
        self.config["batch_size"] = 2
        self.engines = []
        self.patches = [
            patch.object(worker, "load_dataset", side_effect=self.load_dataset),
            patch.object(worker, "GpuSamples", NoGpuSamples),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])
        self.addCleanup(self.temporary.cleanup)

    @staticmethod
    def make_rows(count):
        return [{"id": f"test-{index:05d}",
                 "prompt": (f"Refund request {index}" if index % 2 == 0
                            else f"Reset password request {index}"),
                 "expected": "billing" if index % 2 == 0 else "account"}
                for index in range(count)]

    def load_dataset(self, _cache, *, limit=0, seed=42):
        rows = deepcopy(self.rows[:limit] if limit else self.rows)
        provenance = {"dataset": "CPU test fixture", "revision": "test-revision",
                      "selected_rows": len(rows), "selection": {"limit": limit, "seed": seed}}
        return rows, self.labels[:], provenance, deepcopy(self.train_rows)

    def engine_factory(self, config, labels):
        engine = FakeEngine(config, labels)
        self.engines.append(engine)
        return engine

    def run_worker(self, work_name, *, factory=None, **kwargs):
        with redirect_stdout(io.StringIO()):
            return worker.run(self.config, self.artifacts,
                work_dir=self.directory / work_name,
                recipe_hash="fixed-test-payload",
                engine_factory=factory or self.engine_factory, **kwargs)

    def read_zip(self, summary):
        attempt_id = summary["attempts"][-1]["attempt_id"]
        path = self.artifacts / "exports" / attempt_id / "result.zip"
        return zipfile.ZipFile(path)

    def test_planned_two_batch_stop_and_fresh_worker_complete_all_3080_rows(self):
        self.rows = self.make_rows(3080)
        self.config["batch_size"] = 64
        first = self.run_worker("first-vm", stop_after_batches=2)
        self.assertEqual((first["completed"], first["remaining"], first["complete"]),
                         (128, 2952, False))
        self.assertEqual(first["attempts"][-1]["new_batches"], 2)
        self.assertEqual(len(self.engines[0].calls), 2)
        # Remove VM-local state. Only the simulated external bucket remains.
        shutil.rmtree(self.directory / "first-vm")
        second = self.run_worker("replacement-vm")
        self.assertEqual((second["completed"], second["remaining"], second["complete"]),
                         (3080, 0, True))
        self.assertEqual(len(self.engines), 2)
        self.assertEqual(second["attempts"][-1]["reused_batches"], 2)
        self.assertEqual(second["attempts"][-1]["reused_rows"], 128)
        self.assertEqual(second["attempts"][-1]["new_batches"], 47)
        self.assertEqual(second["attempts"][-1]["new_rows"], 2952)
        calls = [row_id for engine in self.engines for group in engine.calls for row_id in group]
        self.assertEqual(calls, [row["id"] for row in self.rows])
        self.assertEqual(len(set(calls)), 3080)
        with self.read_zip(second) as archive:
            self.assertIsNone(archive.testzip())
            self.assertTrue({"input.csv", "predictions.csv", "review.csv", "mistakes.csv",
                             "report.html", "summary.json", "attempts.json", "run_contract.json",
                             "config.json", "runtime.json", "dataset_provenance.json"}
                            .issubset(archive.namelist()))
            records = list(csv.DictReader(io.StringIO(archive.read("predictions.csv").decode())))
            self.assertEqual([row["id"] for row in records], [row["id"] for row in self.rows])
            self.assertEqual(len(json.loads(archive.read("attempts.json"))), 2)
            exported = json.loads(archive.read("summary.json"))
            self.assertEqual(exported["completed"], 3080)
            self.assertIsNone(exported["cost"]["measured_billed_cost"])

    def test_fully_saved_rerun_does_not_load_an_engine(self):
        self.run_worker("first-vm")
        def forbidden_engine(*_):
            self.fail("A fully saved run must not initialize the model")
        result = self.run_worker("fresh-vm", factory=forbidden_engine)
        attempt = result["attempts"][-1]
        self.assertTrue(result["complete"])
        self.assertEqual((attempt["new_batches"], attempt["new_rows"]), (0, 0))
        self.assertEqual((attempt["reused_batches"], attempt["reused_rows"]), (4, 7))
        self.assertEqual(attempt["model_load_seconds"], 0)
        self.assertEqual(attempt["generation_seconds"], 0)
        self.assertEqual(len(self.engines), 1)

    def test_gold_and_other_metadata_never_change_messages(self):
        original = {"id": "one", "prompt": "Refund this charge", "expected": "billing"}
        changed = {**original, "expected": "NEVER_SEND_THIS_GOLD_FIELD",
                   "private_annotation": "NEVER_SEND_THIS_ANNOTATION"}
        before = worker.messages_for(original, self.labels)
        after = worker.messages_for(changed, self.labels)
        self.assertEqual(before, after)
        serialized = json.dumps(after)
        self.assertNotIn("NEVER_SEND_THIS_GOLD_FIELD", serialized)
        self.assertNotIn("NEVER_SEND_THIS_ANNOTATION", serialized)
        self.assertEqual([item["role"] for item in after], ["system", "user"])
        self.assertEqual(json.loads(after[1]["content"].removeprefix("Request: ")),
                         original["prompt"])

    def test_changed_gold_prompt_or_selection_rejects_saved_run_before_engine_load(self):
        self.run_worker("first-vm", stop_after_batches=2)
        original_rows = deepcopy(self.rows)
        original_batches = len(list((self.artifacts / "batches").iterdir()))
        def forbidden_engine(*_):
            self.fail("Input changes must be rejected before model initialization")
        for kind in ("gold", "prompt", "limit"):
            self.rows = deepcopy(original_rows)
            kwargs = {}
            if kind == "gold":
                self.rows[0]["expected"] = "account"
            elif kind == "prompt":
                self.rows[0]["prompt"] = "Changed request text"
            else:
                kwargs["limit"] = 5
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "different completed contract"):
                self.run_worker("changed-" + kind, factory=forbidden_engine, **kwargs)
        self.assertEqual(len(list((self.artifacts / "batches").iterdir())), original_batches)
        self.assertEqual(len(read_attempts(self.artifacts)), 1)

    def test_wrong_model_output_ids_are_not_saved(self):
        class WrongIds(FakeEngine):
            def generate(self, rows):
                records = super().generate(rows)
                records[0]["id"] = "not-an-input-id"
                return records
        with self.assertRaisesRegex(ValueError, "Output IDs differ"):
            self.run_worker("wrong-id-vm", factory=WrongIds)
        self.assertFalse((self.artifacts / "batches").exists())
        self.assertEqual(read_attempts(self.artifacts), [])

    def test_reordered_or_missing_model_outputs_are_not_saved(self):
        for mode in ("reverse", "missing"):
            class BadOutput(FakeEngine):
                def generate(self, rows):
                    records = super().generate(rows)
                    return records[::-1] if mode == "reverse" else records[:-1]
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "Output IDs differ"):
                self.run_worker("bad-" + mode, factory=BadOutput)
        self.assertFalse((self.artifacts / "batches").exists())


if __name__ == "__main__":
    unittest.main()
