"""Offline checks of partial/corrupt checkpoint recovery and held-out data boundaries."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from checkpoint_store import (ensure_contract, latest_checkpoint, publish_checkpoint,
    restore_checkpoint, safe_relative, verify_published)
from evaluate import LABELS, read_examples, score, normalize
from data_prep import select_rows


def fixture(path, step):
    path.mkdir(parents=True)
    for name in ["optimizer.pt", "scheduler.pt", "rng_state.pth", "adapter_config.json", "adapter_model.safetensors"]:
        (path / name).write_bytes(b"offline-checkpoint-fixture")
    (path / "trainer_state.json").write_text(json.dumps({"global_step": step}))


class RecoveryTests(unittest.TestCase):
    def test_partial_checkpoint_is_not_resumed_and_complete_state_restores(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root / "local", 10)
            published = publish_checkpoint(root / "local", root / "remote", "contract")
            partial = root / "remote/checkpoints/checkpoint-20-abcdef"
            partial.mkdir()
            (partial / "optimizer.pt").write_bytes(b"incomplete")
            found, manifest = latest_checkpoint(root / "remote", "contract")
            self.assertEqual(found, published)
            restored = restore_checkpoint(found, manifest, root / "fresh-container")
            self.assertEqual((restored / "optimizer.pt").read_bytes(), b"offline-checkpoint-fixture")
            self.assertEqual(json.loads((restored / "trainer_state.json").read_text())["global_step"], 10)

    def test_corrupt_newer_checkpoint_falls_back_to_intact_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root / "ten", 10)
            fixture(root / "twenty", 20)
            older = publish_checkpoint(root / "ten", root / "remote", "contract")
            newer = publish_checkpoint(root / "twenty", root / "remote", "contract")
            (newer / "optimizer.pt").write_bytes(b"corrupt")
            found, manifest = latest_checkpoint(root / "remote", "contract")
            self.assertEqual(found, older)
            self.assertEqual(manifest["global_step"], 10)

    def test_adapter_only_is_rejected_as_a_recovery_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("adapter_config.json").write_text("{}")
            with self.assertRaises(ValueError):
                publish_checkpoint(root, root / "remote", "contract")

    def test_changed_run_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_contract(root, {"model": "first"})
            with self.assertRaises(ValueError):
                ensure_contract(root, {"model": "different"})

    def test_checkpoint_manifest_cannot_escape_its_directory(self):
        for value in ["../optimizer.pt", "/tmp/optimizer.pt", "a/../../optimizer.pt"]:
            with self.assertRaises(ValueError):
                safe_relative(value)

    def test_real_data_selection_is_balanced_deterministic_and_disjoint(self):
        labels=["Refund_not_showing_up","reverted_card_payment?"]
        train=[{"id":f"train-{i}-{j}","prompt":f"original training {i} {j}","expected":label}
               for i,label in enumerate(labels) for j in range(5)]
        test=[{"id":f"test-{i}-{j}","prompt":f"original test {i} {j}","expected":label}
              for i,label in enumerate(labels) for j in range(3)]
        train.extend([{**test[0],"id":"overlap-train"},{**train[0],"id":"duplicate-train"}])
        chosen,evaluation,audit=select_rows(train,test,labels,2,1,42)
        self.assertEqual((chosen,evaluation,audit),select_rows(train,test,labels,2,1,42))
        self.assertEqual(len(chosen),4)
        self.assertEqual(len(evaluation),2)
        self.assertEqual(audit["excluded_train_rows_matching_official_test_text"],1)
        self.assertEqual(audit["excluded_duplicate_train_texts"],1)
        self.assertFalse({r["prompt"] for r in chosen}&{r["prompt"] for r in evaluation})
        for label in labels:self.assertEqual(sum(r["expected"]==label for r in chosen),2)

    def test_taxonomy_case_and_punctuation_are_preserved(self):
        self.assertEqual(len(LABELS),77)
        self.assertIn("Refund_not_showing_up",LABELS)
        self.assertIn("reverted_card_payment?",LABELS)
        self.assertEqual(normalize('"Refund_not_showing_up"'),"Refund_not_showing_up")

    def test_invalid_label_is_counted_wrong_not_guessed(self):
        result = score([{"id": "one", "prompt": "Example", "expected": "card_arrival"}], ["Maybe billing or account"])
        self.assertEqual(result["correct"], 0)
        self.assertEqual(result["invalid_predictions"], 1)


if __name__ == "__main__":
    unittest.main()
