"""Dataset preparation tests use tiny verified fixtures, never GPUs or live APIs."""

import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import dataset


def csv_bytes(fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(fields)
    writer.writerows(rows)
    return stream.getvalue().encode()


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.labels = ["card_arrival", "Refund_not_showing_up", "reverted_card_payment?"]
        self.files = {
            "train.csv": csv_bytes(["text", "category"], [(f"Training {index}", label) for index, label in enumerate(self.labels)]),
            "test.csv": csv_bytes(["text", "category"], [(f"Test {index}", label) for index, label in enumerate(self.labels * 2)]),
            "categories.json": json.dumps(self.labels).encode(),
            "LICENSE": b"Fixture license; not a substitute for the real data license.\n",
        }
        self.specs = {}
        for name, data in self.files.items():
            spec = {"path": name if name == "LICENSE" else "banking_data/" + name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            if name != "LICENSE":
                spec["rows"] = {"train.csv": 3, "test.csv": 6, "categories.json": 3}[name]
            self.specs[name] = spec
        self.addCleanup(patch.stopall)
        patch.object(dataset, "SOURCE_FILES", self.specs).start()
        self.urlopen = patch.object(dataset.urllib.request, "urlopen", side_effect=self.open_url).start()

    def open_url(self, request, timeout):
        self.assertEqual(timeout, 60)
        self.assertTrue(request.full_url.startswith(dataset.BASE_URL))
        return io.BytesIO(self.files[request.full_url.rsplit("/", 1)[1]])

    def load(self, **kwargs):
        return dataset.load_dataset(self.directory / "cache", **kwargs)

    def write_csv(self, text):
        path = self.directory / "custom.csv"
        path.write_text(text)
        return path

    def test_pinned_downloads_separate_training_and_keep_labels(self):
        rows, labels, provenance, training = self.load()
        self.assertEqual(labels, self.labels)
        self.assertEqual(len(rows), 6)
        self.assertEqual(len(training), 3)
        self.assertTrue(all(row["id"].startswith("banking77-test-") for row in rows))
        self.assertTrue(all(row["id"].startswith("banking77-train-") for row in training))
        self.assertFalse({row["id"] for row in rows} & {row["id"] for row in training})
        self.assertEqual(provenance["revision"], dataset.REVISION)
        self.assertEqual(provenance["selected_rows"], 6)
        self.assertEqual(provenance["selection"]["split"], "test")
        self.assertEqual(self.urlopen.call_count, 4)

    def test_seeded_limit_has_stable_source_record_ids(self):
        full, _, provenance, _ = self.load()
        limited, _, limited_provenance, _ = self.load(limit=2)
        self.assertEqual(limited, full[:2])
        expected_order = list(range(1, 7))
        random.Random(42).shuffle(expected_order)
        self.assertEqual([row["id"] for row in full], [f"banking77-test-{index:06d}" for index in expected_order])
        for row in full:
            index = int(row["id"].rsplit("-", 1)[1]) - 1
            self.assertEqual(row["prompt"], f"Test {index}")
            self.assertEqual(row["expected"], self.labels[index % 3])
        self.assertNotEqual(provenance["input_sha256"], limited_provenance["input_sha256"])
        self.assertNotEqual(full, self.load(seed=7)[0])

    def test_valid_cache_requires_no_new_downloads(self):
        first = self.load()
        self.urlopen.reset_mock()
        self.assertEqual(first, self.load())
        self.urlopen.assert_not_called()

    def test_cached_bytes_are_rechecked_before_reuse(self):
        self.load()
        path = self.directory / "cache" / f"banking77-{dataset.REVISION}" / "test.csv"
        data = path.read_bytes()
        path.write_bytes(b"X" + data[1:])
        with self.assertRaisesRegex(dataset.DatasetError, "verification failed"):
            self.load()

    def test_failed_download_is_not_committed(self):
        self.files["train.csv"] = b"corrupt"
        with self.assertRaisesRegex(dataset.DatasetError, "verification failed"):
            self.load()
        cache = self.directory / "cache" / f"banking77-{dataset.REVISION}"
        self.assertEqual(list(cache.iterdir()), [])

    def test_failed_atomic_rename_removes_temporary_file(self):
        with patch.object(dataset.os, "replace", side_effect=OSError("fixture disk error")):
            with self.assertRaises(dataset.DatasetError):
                self.load()
        cache = self.directory / "cache" / f"banking77-{dataset.REVISION}"
        self.assertEqual(list(cache.iterdir()), [])

    def test_symlink_cache_entry_is_rejected(self):
        cache = self.directory / "cache" / f"banking77-{dataset.REVISION}"
        cache.mkdir(parents=True)
        target = self.directory / "outside"
        target.write_bytes(self.files["train.csv"])
        (cache / "train.csv").symlink_to(target)
        with self.assertRaisesRegex(dataset.DatasetError, "symlink"):
            self.load()

    def test_invalid_limits_fail_without_network(self):
        for limit in [-1, 7, True, 1.5]:
            with self.subTest(limit=limit), self.assertRaises(dataset.DatasetError):
                self.load(limit=limit)
        with self.assertRaises(dataset.DatasetError):
            self.load(seed="42")
        self.urlopen.assert_not_called()

    def test_source_parser_rejects_unknown_label_wrong_schema_and_count(self):
        cases = [
            csv_bytes(["text", "category"], [("Hello", "unknown")]),
            csv_bytes(["prompt", "category"], [("Hello", self.labels[0])]),
            csv_bytes(["text", "category"], [("Hello", self.labels[0])]),
        ]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(dataset.DatasetError):
                dataset._upstream_rows(data, "test", self.labels)

    def test_unlabelled_custom_ids_need_no_dataset_prefix(self):
        path = self.write_csv('id,prompt\nclient/order 123,"Please check my card, thanks"\n')
        self.assertEqual(dataset.load_csv(path, self.labels), [{"id": "client/order 123", "prompt": "Please check my card, thanks", "expected": ""}])

    def test_custom_expected_preserves_exact_taxonomy(self):
        path = self.write_csv('id,prompt,expected\none,Where is the refund?,Refund_not_showing_up\ntwo,Another request,\n')
        self.assertEqual([row["expected"] for row in dataset.load_csv(path, self.labels)], ["Refund_not_showing_up", ""])
        path.write_text('id,prompt,expected\none,Where is the refund?,refund_not_showing_up\n')
        with self.assertRaisesRegex(dataset.DatasetError, "Unknown expected"):
            dataset.load_csv(path, self.labels)

    def test_custom_csv_rejects_bad_headers_rows_and_duplicates(self):
        cases = [
            "id,text\none,Hello\n",
            "id,prompt,prompt\none,Hello,Hello\n",
            "id,prompt\none\n",
            "id,prompt\none,Hello,extra\n",
            "id,prompt\n,Hello\n",
            "id,prompt\none, \n",
            "id,prompt\none,Hello\none,Again\n",
            "id,prompt\n",
            'id,prompt\none,"unterminated\n',
        ]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(dataset.DatasetError):
                dataset.load_csv(self.write_csv(text), self.labels)

    def test_custom_size_and_field_limits(self):
        path = self.write_csv("id,prompt\none,Hello\ntwo,Again\n")
        for constant, value in [("MAX_INPUT_BYTES", 5), ("MAX_ROWS", 1), ("MAX_ID_CHARS", 2), ("MAX_PROMPT_CHARS", 3)]:
            with self.subTest(constant=constant), patch.object(dataset, constant, value), self.assertRaises(dataset.DatasetError):
                dataset.load_csv(path, self.labels)

    def test_prepare_cli_writes_only_selected_test_rows(self):
        spec = importlib.util.spec_from_file_location("recipe_prepare_data", ROOT / "scripts/prepare_data.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = self.directory / "prepared.csv"
        with patch("sys.stdout", new_callable=io.StringIO):
            result = module.main(["--limit", "2", "--seed", "7", "--output", str(output), "--cache-dir", str(self.directory / "cache")])
        self.assertEqual(result, 0)
        rows = dataset.load_csv(output, self.labels)
        self.assertEqual(rows, self.load(limit=2, seed=7)[0])
        self.assertTrue(all("-test-" in row["id"] for row in rows))


if __name__ == "__main__":
    unittest.main()
