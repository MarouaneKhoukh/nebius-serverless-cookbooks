"""CPU checks for honest metrics, report safety and a train-only baseline."""

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from baseline import predict
from report import export_results


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.logo = Path(__file__).resolve().parents[1] / "docs/brand/nebius-logo.svg"
        self.rows = [{"id": "one", "prompt": "refund please", "expected": "billing"},
                     {"id": "two", "prompt": "card charged twice", "expected": "billing"},
                     {"id": "three", "prompt": "reset password", "expected": "account"}]

    def tearDown(self):
        self.temporary.cleanup()

    def records(self):
        return [{**row, "predicted": prediction, "response": prediction or "unknown", "valid": prediction is not None,
                 "truncated": False, "input_tokens": 10, "output_tokens": 2, "batch_id": "batch-1"}
                for row, prediction in zip(self.rows, ("billing", "account", None))]

    def test_metrics_count_invalid_as_wrong_and_compare_identical_rows(self):
        baseline = {"one": "billing", "two": "billing", "three": "account"}
        result = export_results(self.root, self.rows, self.records(), {"baseline_predictions": baseline}, self.logo)
        self.assertAlmostEqual(result["accuracy"], 1 / 3)
        self.assertAlmostEqual(result["macro_f1"], 1 / 3)
        self.assertEqual(result["invalid_labels"], 1)
        self.assertEqual(result["baseline"]["rows"], result["completed"])
        self.assertEqual(result["baseline"]["accuracy"], 1)
        self.assertEqual(result["baseline_disagreements"], 1)
        self.assertEqual(result["input_tokens"], 30)
        self.assertIsNone(result["cost"]["measured_total_usd"])
        self.assertTrue(result["complete"])
        self.assertEqual(json.loads((self.root / "summary.json").read_text()), result)

    def test_partial_run_and_incomplete_baseline_are_not_misrepresented(self):
        result = export_results(self.root, self.rows, self.records()[:2], {"baseline_predictions": {"one": "billing"}, "total": 999}, self.logo)
        self.assertEqual((result["total"], result["completed"], result["remaining"]), (3, 2, 1))
        self.assertFalse(result["complete"])
        self.assertFalse(result["baseline"]["complete"])
        self.assertIsNone(result["baseline"]["accuracy"])

    def test_review_distinguishes_disagreement_from_gold_mistakes(self):
        records = [{**row, "predicted": row["expected"], "response": row["expected"], "valid": True, "truncated": False} for row in self.rows]
        records[2]["truncated"] = True
        result = export_results(self.root, self.rows, records, {"baseline_predictions": {"one": "account", "two": "billing", "three": "account"}}, self.logo)
        with (self.root / "review.csv").open(newline="") as source:
            review = list(csv.DictReader(source))
        with (self.root / "mistakes.csv").open(newline="") as source:
            mistakes = list(csv.DictReader(source))
        self.assertEqual([row["id"] for row in review], ["one", "three"])
        self.assertEqual([row["id"] for row in mistakes], ["three"])
        self.assertIn("disagreement", review[0]["review_reasons"])
        self.assertIn("truncated", review[1]["review_reasons"])
        self.assertEqual(result["truncated"], 1)
        self.assertIn("not confidence", result["review_note"])

    def test_report_escapes_text_and_metadata_and_keeps_official_brand(self):
        payload = '<script>alert("x")</script>'
        rows = [{"id": "unsafe", "prompt": payload, "expected": "billing"}]
        records = [{**rows[0], "predicted": payload, "response": payload, "valid": True}]
        export_results(self.root, rows, records, {"model": payload, "dataset": {"name": payload}}, self.logo)
        report = (self.root / "report.html").read_text()
        self.assertNotIn(payload, report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn(self.logo.read_text(), report)
        self.assertIn("Powered by Nebius Serverless AI", report)
        self.assertIn("Classify a Support Backlog with Qwen", report)
        self.assertIn("textContent", report)
        self.assertNotIn("innerHTML", report)
        bad_logo = self.root / "bad.svg"
        bad_logo.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        with self.assertRaises(ValueError):
            export_results(self.root, rows, [], {}, bad_logo)

    def test_export_rejects_duplicate_unknown_or_changed_saved_rows(self):
        for records in ([self.records()[0], self.records()[0]], [{**self.records()[0], "id": "other"}], [{**self.records()[0], "prompt": "changed"}]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                export_results(self.root, self.rows, records, {}, self.logo)

    def test_baseline_learns_words_and_bigrams_without_gold_leakage(self):
        train = [{"id": "train-a", "prompt": "reset forgotten password", "expected": "account"},
                 {"id": "train-b", "prompt": "password account login", "expected": "account"},
                 {"id": "train-c", "prompt": "refund credit charged card", "expected": "billing"},
                 {"id": "train-d", "prompt": "refund payment invoice", "expected": "billing"}]
        result = predict(train, self.rows, ["account", "billing"])
        self.assertEqual(result, {"one": "billing", "two": "billing", "three": "account"})
        changed_gold = [{**row, "expected": "account" if row["expected"] == "billing" else "billing"} for row in self.rows]
        self.assertEqual(result, predict(train, changed_gold, ["account", "billing"]))
        opposite_bigrams = [{"id": "t1", "prompt": "red blue", "expected": "forward"}, {"id": "t2", "prompt": "blue red", "expected": "backward"}]
        self.assertEqual(predict(opposite_bigrams, [{"id": "q", "prompt": "red blue"}], ["forward", "backward"]), {"q": "forward"})

    def test_baseline_rejects_overlapping_splits_and_missing_training(self):
        with self.assertRaises(ValueError):
            predict([], self.rows, ["billing", "account"])
        with self.assertRaises(ValueError):
            predict(self.rows, self.rows, ["billing", "account"])

    def test_unlabelled_inputs_keep_predictions_without_inventing_accuracy(self):
        rows = [{**row, "expected": ""} for row in self.rows]
        records = [{**record, "expected": ""} for record in self.records()]
        result = export_results(self.root, rows, records, {
            "labels": ["account", "billing"],
            "baseline_predictions": {"one": "account", "two": "account", "three": "account"},
        }, self.logo)
        self.assertEqual((result["completed"], result["scored"], result["unlabelled"]), (3, 0, 3))
        self.assertIsNone(result["accuracy"])
        self.assertIsNone(result["macro_f1"])
        self.assertIsNone(result["baseline"]["accuracy"])
        self.assertEqual(result["mistakes"], 0)
        self.assertEqual(result["invalid_labels"], 1)
        self.assertEqual(result["review_rows"], 2)
        self.assertEqual(result["confusions"], [])
        with (self.root / "predictions.csv").open(newline="") as source:
            predictions = list(csv.DictReader(source))
        self.assertEqual(predictions[0]["correct"], "")
        self.assertIn("disagreement", predictions[0]["review_reasons"])
        self.assertNotIn("gold label mismatch", predictions[0]["review_reasons"])
        with (self.root / "mistakes.csv").open(newline="") as source:
            self.assertEqual(list(csv.DictReader(source)), [])

    def test_mixed_labels_score_only_gold_and_preserve_full_taxonomy(self):
        rows = [{**self.rows[0], "expected": "billing"}, {**self.rows[1], "expected": ""}]
        records = [{**rows[0], "predicted": "account", "response": "account", "valid": True},
                   {**rows[1], "predicted": "technical", "response": "technical", "valid": True}]
        result = export_results(self.root, rows, records, {
            "labels": ["billing", "account", "technical"],
            "baseline_predictions": {"one": "billing", "two": "technical"},
        }, self.logo)
        self.assertEqual(result["scored"], 1)
        self.assertEqual(result["metrics"]["rows"], result["baseline"]["rows"])
        self.assertEqual(result["accuracy"], 0)
        self.assertEqual(result["baseline"]["accuracy"], 1)
        self.assertEqual(result["invalid_labels"], 0)
        self.assertEqual(result["mistakes"], 1)
        self.assertEqual(result["label_counts"]["predicted"]["technical"], 1)


if __name__ == "__main__":
    unittest.main()
