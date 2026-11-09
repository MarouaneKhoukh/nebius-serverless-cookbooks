import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluate import score
from runner import RecipeError, load_rows


class EvaluationTests(unittest.TestCase):
    def test_invalid_answers_count_as_incorrect(self):
        records = [{"id": "a", "expected": "billing", "label": "billing"}, {"id": "b", "expected": "account", "label": None}, {"id": "c", "expected": "technical", "label": "account"}]
        summary, rows = score(records, 3)
        self.assertEqual(summary["correct"], 1)
        self.assertEqual(summary["incorrect"], 2)
        self.assertEqual(summary["invalid_predictions"], 1)
        self.assertAlmostEqual(summary["accuracy"], 1 / 3)
        self.assertEqual(summary["confusion_matrix"]["account"]["invalid"], 1)
        self.assertTrue(summary["complete"])

    def test_partial_report_cannot_claim_a_complete_evaluation(self):
        summary, _ = score([{"id": "a", "expected": "billing", "label": "billing"}], 30)
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["remaining"], 29)

    def test_bundled_dataset_is_balanced_and_separate(self):
        rows = load_rows(Path(__file__).resolve().parents[1] / "data" / "evaluation.csv", evaluation=True)
        self.assertEqual(len(rows), 30)
        self.assertEqual({label: sum(row["expected"] == label for row in rows) for label in ("billing", "technical", "account")}, {"billing": 10, "technical": 10, "account": 10})


if __name__ == "__main__":
    unittest.main()
