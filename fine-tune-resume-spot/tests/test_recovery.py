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
from evaluate import read_examples, score


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

    def test_data_is_separate_balanced_and_small_enough_to_inject(self):
        train_path = ROOT / "data/train.jsonl"
        train = [json.loads(line) for line in train_path.read_text().splitlines()]
        test = read_examples(ROOT / "data/test.csv")
        self.assertEqual(len(train), 120)
        self.assertEqual(len(test), 30)
        self.assertLessEqual(train_path.stat().st_size, 65536)
        prompts = {row["messages"][1]["content"] for row in train}
        self.assertEqual(len(prompts), len(train))
        self.assertFalse(prompts & {row["prompt"] for row in test})
        for label in ["billing", "technical", "account"]:
            self.assertEqual(sum(row["messages"][-1]["content"] == label for row in train), 40)

    def test_invalid_label_is_counted_wrong_not_guessed(self):
        result = score([{"id": "one", "prompt": "Example", "expected": "billing"}], ["Maybe billing or account"])
        self.assertEqual(result["correct"], 0)
        self.assertEqual(result["invalid_predictions"], 1)


if __name__ == "__main__":
    unittest.main()
