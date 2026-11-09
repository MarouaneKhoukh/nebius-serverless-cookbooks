"""Offline recovery checks for immutable Object Storage artifact publications."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import artifacts


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "bucket"
        self.contract = {"model": "test-model", "revision": "pinned", "input": "abc"}
        self.contract_hash = artifacts.digest_json(self.contract)
        self.partitions = [["a", "b"], ["c"]]
        self.records = [{"id": "a", "response": "billing"},
                        {"id": "b", "response": "account"}]

    def tearDown(self):
        self.temporary.cleanup()

    def publish(self, index=0, records=None, **stats):
        return artifacts.publish_batch(self.root, self.contract_hash, index,
            self.records if records is None else records, self.partitions[index], stats)

    def marker(self, directory):
        return json.loads((directory / "complete.json").read_text())

    def rewrite_marker(self, directory, **changes):
        value = {**self.marker(directory), **changes}
        (directory / "complete.json").write_text(json.dumps(value))

    def test_digest_is_canonical_and_rejects_nonfinite_numbers(self):
        self.assertEqual(artifacts.digest_json({"b": "café", "a": 1}),
                         artifacts.digest_json({"a": 1, "b": "café"}))
        with self.assertRaises(ValueError):
            artifacts.digest_json({"seconds": float("nan")})

    def test_contract_reuses_matching_complete_copy(self):
        self.assertEqual(artifacts.ensure_contract(self.root, self.contract), self.contract_hash)
        self.assertEqual(artifacts.ensure_contract(self.root, dict(self.contract)), self.contract_hash)
        self.assertEqual(len(list((self.root / "contracts").iterdir())), 1)

    def test_contract_rejects_different_valid_publication(self):
        artifacts.ensure_contract(self.root, self.contract)
        with self.assertRaisesRegex(ValueError, "different completed contract"):
            artifacts.ensure_contract(self.root, {**self.contract, "revision": "changed"})

    def test_incomplete_or_corrupt_contract_does_not_wedge_recovery(self):
        partial = self.root / "contracts" / "partial"
        partial.mkdir(parents=True)
        (partial / "contract.json").write_text('{"unfinished":')
        artifacts.ensure_contract(self.root, self.contract)
        complete = next(path for path in (self.root / "contracts").iterdir()
                        if (path / "complete.json").exists())
        (complete / "contract.json").write_text("truncated")
        self.assertEqual(artifacts.ensure_contract(self.root, self.contract), self.contract_hash)

    def test_batch_round_trip_preserves_row_order_and_stats(self):
        first = self.publish(generation_seconds=1.2)
        second = self.publish(1, [{"id": "c", "response": "technical"}], generation_seconds=0.5)
        loaded = artifacts.load_batches(self.root, self.contract_hash, self.partitions)
        self.assertEqual(list(loaded), [0, 1])
        self.assertEqual(loaded[0]["records"], self.records)
        self.assertEqual(loaded[0]["manifest"]["stats"], {"generation_seconds": 1.2})
        self.assertEqual(self.marker(first)["bytes"], (first / "records.jsonl").stat().st_size)
        self.assertEqual(self.marker(second)["row_ids"], ["c"])

    def test_resume_keeps_valid_older_generation_when_latest_is_corrupt(self):
        first = self.publish(generation_seconds=1.0)
        latest = self.publish(generation_seconds=2.0)
        self.rewrite_marker(first, published_at="2026-01-01T00:00:00+00:00")
        self.rewrite_marker(latest, published_at="2026-01-02T00:00:00+00:00")
        self.assertEqual(artifacts.load_batches(self.root, self.contract_hash, self.partitions)
                         [0]["manifest"]["stats"]["generation_seconds"], 2.0)
        (latest / "records.jsonl").write_text("corrupt")
        self.assertEqual(artifacts.load_batches(self.root, self.contract_hash, self.partitions)
                         [0]["manifest"]["stats"]["generation_seconds"], 1.0)

    def test_batch_without_marker_or_with_partial_marker_is_ignored(self):
        first = self.publish()
        (first / "complete.json").unlink()
        self.assertEqual(artifacts.load_batches(self.root, self.contract_hash, self.partitions), {})
        (first / "complete.json").write_text('{"schema":')
        self.assertEqual(artifacts.load_batches(self.root, self.contract_hash, self.partitions), {})

    def test_interruption_before_marker_never_commits_batch(self):
        with patch.object(artifacts, "_write_json", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(artifacts.load_batches(self.root, self.contract_hash, self.partitions), {})
        self.publish()
        self.assertEqual(len(artifacts.load_batches(self.root, self.contract_hash, self.partitions)), 1)

    def test_complete_wrong_contract_is_rejected(self):
        self.publish()
        with self.assertRaisesRegex(ValueError, "different contract"):
            artifacts.load_batches(self.root, "f" * 64, self.partitions)

    def test_wrong_order_and_out_of_range_batches_are_not_reused(self):
        directory = self.publish()
        self.rewrite_marker(directory, row_ids=["b", "a"])
        self.assertEqual(artifacts.load_batches(self.root, self.contract_hash, self.partitions), {})
        self.rewrite_marker(directory, row_ids=["a", "b"], index=2)
        self.assertEqual(artifacts.load_batches(self.root, self.contract_hash, self.partitions), {})

    def test_corrupt_record_ids_are_rejected_even_with_matching_checksum(self):
        directory = self.publish()
        data = b'{"id":"a"}\n{"id":"a"}\n'
        (directory / "records.jsonl").write_bytes(data)
        self.rewrite_marker(directory, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual(artifacts.load_batches(self.root, self.contract_hash, self.partitions), {})

    def test_partition_ids_are_unique_across_all_batches(self):
        for partitions in ([["a"], ["a"]], [["a", "a"]], [[]]):
            with self.subTest(partitions=partitions), self.assertRaises(ValueError):
                artifacts.load_batches(self.root, self.contract_hash, partitions)

    def test_publication_rejects_mismatched_rows_and_invalid_indexes(self):
        for index, records, ids in ((-1, self.records, ["a", "b"]),
                                     (True, self.records, ["a", "b"]),
                                     (0, self.records, ["b", "a"]),
                                     (0, self.records, ["a", "a"]),
                                     (0, self.records[:1], ["a", "b"])):
            with self.subTest(index=index, ids=ids), self.assertRaises(ValueError):
                artifacts.publish_batch(self.root, self.contract_hash, index, records, ids, {})
        self.assertFalse((self.root / "batches").exists())

    def test_read_attempts_ignores_partial_and_corrupt_summaries(self):
        first = artifacts.publish_attempt(self.root, "first", {"completed_batches": 1})
        partial = artifacts.publish_attempt(self.root, "partial", {"completed_batches": 2})
        broken = artifacts.publish_attempt(self.root, "broken", {"completed_batches": 3})
        (partial / "complete.json").unlink()
        (broken / "summary.json").write_text("broken")
        self.assertEqual(artifacts.read_attempts(self.root), [{"completed_batches": 1}])
        self.assertTrue((first / "complete.json").is_file())

    def test_attempt_ids_cannot_escape_and_completed_attempts_are_immutable(self):
        for value in ("../escape", "/absolute", ".", "", "a/b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                artifacts.publish_attempt(self.root, value, {})
        artifacts.publish_attempt(self.root, "attempt-one", {"value": 1})
        with self.assertRaises(FileExistsError):
            artifacts.publish_attempt(self.root, "attempt-one", {"value": 2})
        self.assertEqual(artifacts.read_attempts(self.root), [{"value": 1}])

    def local_zip(self):
        path = Path(self.temporary.name) / "local.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("responses.csv", "id,response\na,billing\n")
        return path

    def test_bundle_is_verified_and_published_with_marker(self):
        local = self.local_zip()
        directory = artifacts.publish_bundle(self.root, local, self.contract_hash, "attempt-1")
        marker = self.marker(directory)
        self.assertEqual((directory / "result.zip").read_bytes(), local.read_bytes())
        self.assertEqual(marker["sha256"], hashlib.sha256(local.read_bytes()).hexdigest())
        self.assertEqual(marker["bytes"], local.stat().st_size)
        self.assertEqual(marker["contract_hash"], self.contract_hash)
        with self.assertRaises(FileExistsError):
            artifacts.publish_bundle(self.root, local, self.contract_hash, "attempt-1")

    def test_partial_bundle_is_not_mistaken_for_success(self):
        local = self.local_zip()
        with patch.object(artifacts, "_write_json", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                artifacts.publish_bundle(self.root, local, self.contract_hash, "partial")
        self.assertTrue((self.root / "exports" / "partial" / "result.zip").exists())
        self.assertFalse((self.root / "exports" / "partial" / "complete.json").exists())
        complete = artifacts.publish_bundle(self.root, local, self.contract_hash, "fresh-attempt")
        self.assertTrue((complete / "complete.json").exists())

    def test_incomplete_local_zip_is_rejected_before_publication(self):
        local = Path(self.temporary.name) / "broken.zip"
        local.write_bytes(b"PK incomplete")
        with self.assertRaisesRegex(ValueError, "incomplete or invalid"):
            artifacts.publish_bundle(self.root, local, self.contract_hash, "attempt")
        self.assertFalse((self.root / "exports").exists())

    def test_publication_does_not_use_posix_metadata_operations(self):
        with patch("os.replace", side_effect=AssertionError("rename unsupported")), \
                patch("os.rename", side_effect=AssertionError("rename unsupported")), \
                patch("os.chmod", side_effect=AssertionError("chmod unsupported")), \
                patch("shutil.copystat", side_effect=AssertionError("metadata unsupported")):
            artifacts.ensure_contract(self.root, self.contract)
            self.publish()
            artifacts.publish_attempt(self.root, "attempt", {"complete": True})
            artifacts.publish_bundle(self.root, self.local_zip(), self.contract_hash, "attempt")


if __name__ == "__main__":
    unittest.main()
