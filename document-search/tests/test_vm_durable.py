"""Offline integrity/recovery checks using deterministic mock vectors, not a model."""
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "vm" / "durable.py"
SPEC = importlib.util.spec_from_file_location("vm_durable_tested", SOURCE)
durable = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = durable
SPEC.loader.exec_module(durable)


def documents(count=4, words=14):
    return [{"id": f"doc-{index:04d}", "title": f"Fixture {index}",
             "source_url": f"https://example.invalid/doc/{index}",
             "text": " ".join(f"word{number}" for number in range(words))}
            for index in range(count)]


def config(**changes):
    values = {"manifest_sha256": "a" * 64, "model": "mock-encoder",
              "model_revision": "b" * 40, "dimensions": 3, "chunk_words": 20,
              "encoder_settings": {"normalize": True, "pooling": "last-token",
                                   "max_length": 8192, "dtype": "float16"}}
    return durable.RunConfig(**{**values, **changes})


class MockEncoder:
    def __init__(self):
        self.batches = []

    def __call__(self, texts):
        self.batches.append(list(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeMissing(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.puts = []
        self.list_calls = []
        self.corrupt_put = False

    def get_object(self, *, Bucket, Key):
        try:
            return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}
        except KeyError:
            raise FakeMissing() from None

    def put_object(self, *, Bucket, Key, Body):
        self.puts.append((Bucket, Key))
        self.objects[(Bucket, Key)] = Body + (b"changed" if self.corrupt_put else b"")

    def list_objects_v2(self, *, Bucket, Prefix, ContinuationToken=None):
        self.list_calls.append(Prefix)
        keys = sorted(key for bucket, key in self.objects if bucket == Bucket and key.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start:start + 2]
        result = {"Contents": [{"Key": key} for key in page],
                  "IsTruncated": start + 2 < len(keys)}
        if result["IsTruncated"]:
            result["NextContinuationToken"] = str(start + 2)
        return result


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "state"
        self.store = durable.LocalStore(self.root)
        self.docs = documents()
        self.config = config()

    def tearDown(self):
        self.directory.cleanup()

    def index(self, **kwargs):
        return durable.index_documents(self.docs, self.store, MockEncoder(), self.config, **kwargs)

    def assert_resume_rejected(self, docs=None, configuration=None, store=None):
        encoder = Mock(side_effect=AssertionError("must reject before encoding"))
        with self.assertRaises(durable.DurableError):
            durable.index_documents(self.docs if docs is None else docs,
                                    self.store if store is None else store, encoder,
                                    self.config if configuration is None else configuration)
        encoder.assert_not_called()

    def first_chunk_path(self):
        return next(self.root.glob("chunks/*/*.json"))

    def test_global_batching_and_complete_reuse(self):
        encoder = MockEncoder()
        first = durable.index_documents(self.docs, self.store, encoder, self.config, batch_size=3)
        self.assertEqual([len(batch) for batch in encoder.batches], [3, 1])
        self.assertEqual((first["documents_completed"], first["documents_new"], first["chunks_new"]), (4, 4, 4))
        self.assertTrue(first["complete"])
        second_encoder = Mock(side_effect=AssertionError("completed vectors must be reused"))
        second = durable.index_documents(self.docs, self.store, second_encoder, self.config)
        self.assertEqual((second["documents_reused"], second["chunks_reused"], second["documents_new"]), (4, 4, 0))
        second_encoder.assert_not_called()
        for key in ("scan_seconds", "embedding_seconds", "save_seconds", "wall_seconds"):
            self.assertGreaterEqual(first[key], 0.0)
        self.assertEqual(second["embedding_seconds"], 0.0)

    def test_model_manifest_encoder_and_chunk_changes_fail_closed(self):
        self.index()
        alternatives = [
            replace(self.config, manifest_sha256="c" * 64),
            replace(self.config, model="different-model"),
            replace(self.config, model_revision="c" * 40),
            replace(self.config, dimensions=4),
            replace(self.config, chunk_words=10),
            replace(self.config, encoder_settings={**self.config.encoder_settings, "max_length": 4096}),
        ]
        before = {key: self.store.get(key) for key in self.store.keys()}
        for alternative in alternatives:
            with self.subTest(config=alternative):
                self.assert_resume_rejected(configuration=alternative)
        self.assertEqual(before, {key: self.store.get(key) for key in self.store.keys()})

    def test_document_text_metadata_id_and_order_changes_fail_closed(self):
        self.index()
        for field, value in [("text", "different content"), ("title", "different title"),
                             ("source_url", "https://example.invalid/changed"), ("id", "different-id")]:
            changed = json.loads(json.dumps(self.docs))
            changed[0][field] = value
            with self.subTest(field=field):
                self.assert_resume_rejected(docs=changed)
        self.assert_resume_rejected(docs=list(reversed(self.docs)))

    def test_chunk_vector_corruption_and_wrong_dimension_are_rejected(self):
        self.index()
        path = self.first_chunk_path()
        original = path.read_bytes()
        for vector in ([0.0, 1.0, 0.0], [1.0, 0.0], [float("nan"), 0.0, 1.0],
                       [float("inf"), 0.0, 1.0], [True, 0.0, 1.0]):
            value = json.loads(original)
            value["vector"] = vector
            path.write_text(json.dumps(value))
            with self.subTest(vector=vector):
                self.assert_resume_rejected()
            path.write_bytes(original)

    def test_changed_chunk_text_and_completion_marker_are_rejected(self):
        self.index()
        chunk = self.first_chunk_path()
        original = chunk.read_bytes()
        changed = json.loads(original)
        changed["text"] = "changed text"
        chunk.write_text(json.dumps(changed))
        self.assert_resume_rejected()
        chunk.write_bytes(original)
        marker = next(self.root.glob("documents/*.json"))
        original_marker = marker.read_bytes()
        value = json.loads(original_marker)
        value["chunks"] = []
        marker.write_text(json.dumps(value))
        self.assert_resume_rejected()
        marker.write_bytes(original_marker)
        chunk.unlink()
        self.assert_resume_rejected()

    def test_missing_descriptor_unknown_objects_and_bad_json_are_rejected(self):
        self.index()
        run = self.root / "run.json"
        original = run.read_bytes()
        run.unlink()
        self.assert_resume_rejected()
        run.write_bytes(original)
        unknown = self.root / "unexpected.json"
        unknown.write_text("{}")
        self.assert_resume_rejected()
        unknown.unlink()
        self.first_chunk_path().write_text('{"id":"a","id":"b"}')
        self.assert_resume_rejected()

    def test_hook_failure_after_chunk_before_marker_reuses_chunk_without_reembedding(self):
        docs = documents(1)
        hook = Mock(side_effect=RuntimeError("injected after durable chunk"))
        with self.assertRaisesRegex(RuntimeError, "injected"):
            durable.index_documents(docs, self.store, MockEncoder(), self.config,
                                    after_chunk_saved=hook)
        snapshot = durable.inspect_documents(docs, self.store, self.config)
        self.assertEqual(snapshot["stats"]["documents_completed"], 0)
        self.assertEqual(snapshot["stats"]["chunks_saved"], 1)
        self.assertEqual(list(self.root.glob("documents/*.json")), [])
        encoder = Mock(side_effect=AssertionError("the unmarked chunk is already durable"))
        resumed = durable.index_documents(docs, self.store, encoder, self.config)
        self.assertEqual((resumed["documents_new"], resumed["documents_reused"],
                          resumed["chunks_reused"], resumed["chunks_new"]), (1, 0, 1, 0))
        self.assertTrue(resumed["complete"])
        encoder.assert_not_called()

    def test_midway_batch_storage_failure_reuses_unfinished_document_chunks(self):
        docs = documents(2, words=51)  # Three chunks per document with chunk_words=20.

        class FailingStore(durable.LocalStore):
            chunks = 0

            def put(self, key, payload):
                if key.startswith("chunks/"):
                    self.chunks += 1
                    if self.chunks == 3:
                        raise RuntimeError("injected halfway through a saved batch")
                return super().put(key, payload)

        failing = FailingStore(self.root)
        with self.assertRaisesRegex(RuntimeError, "halfway"):
            durable.index_documents(docs, failing, MockEncoder(), self.config, batch_size=4)
        initial = durable.inspect_documents(docs, self.store, self.config)
        self.assertEqual((initial["stats"]["documents_completed"], initial["stats"]["chunks_saved"]), (0, 2))
        encoder = MockEncoder()
        resumed = durable.index_documents(docs, self.store, encoder, self.config, batch_size=4)
        self.assertEqual(sum(map(len, encoder.batches)), 4)
        self.assertEqual((resumed["chunks_reused"], resumed["chunks_new"], resumed["documents_new"]), (2, 4, 2))
        self.assertTrue(resumed["complete"])

    def test_invalid_encoder_batch_saves_no_chunks(self):
        for values in ([[1.0, 0.0, 0.0]],
                       [[1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
                       [[1.0, 0.0, 0.0], [1.0, float("nan"), 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]):
            with self.subTest(values=values), self.assertRaises(durable.DurableError):
                durable.index_documents(self.docs, self.store, lambda _: values, self.config, batch_size=4)
            self.assertEqual(list(self.root.glob("chunks/*/*.json")), [])
            self.assertEqual(list(self.root.glob("documents/*.json")), [])

    def test_partial_load_requires_completion_and_preserves_metadata(self):
        self.index(stop_after_documents=2)
        with self.assertRaises(durable.DurableError):
            durable.load_records(self.docs, self.store, self.config)
        records = durable.load_records(self.docs, self.store, self.config, require_complete=False)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["document_id"], self.docs[0]["id"])
        self.assertEqual(records[0]["source"], self.docs[0]["id"])
        self.assertEqual(records[0]["title"], self.docs[0]["title"])
        self.assertEqual(records[0]["source_url"], self.docs[0]["source_url"])

    def test_corrupt_object_in_unselected_document_is_still_checked(self):
        self.index()
        self.first_chunk_path().write_text("{}")
        encoder = Mock()
        with self.assertRaises(durable.DurableError):
            durable.index_documents(self.docs, self.store, encoder, self.config, stop_after_documents=1)
        encoder.assert_not_called()

    def test_local_immutable_writes_and_staging(self):
        self.store.put_json("sample.json", {"value": 1})
        with self.assertRaises(durable.DurableError):
            self.store.put_json("sample.json", {"value": 2})
        (self.root / ".pending-uncommitted").write_text("partial")
        self.assertEqual(self.store.keys(), ["sample.json"])
        for key in ("../outside", "/absolute", "a//b", "a/../b"):
            with self.subTest(key=key), self.assertRaises(durable.DurableError):
                self.store.get(key)

    def test_1000_documents_resume_600_then_400_in_fresh_processes(self):
        code = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from durable import RunConfig, LocalStore, index_documents
docs = [{"id": "doc-%04d" % i, "title": "Fixture %d" % i,
         "source_url": "https://example.invalid/doc/%d" % i,
         "text": "one two three four five six seven eight nine ten eleven twelve"}
        for i in range(1000)]
settings = RunConfig("a" * 64, "mock-encoder", "b" * 40, 3, chunk_words=20)
encoded = []
def mock_encoder(texts):
    encoded.extend(texts)
    return [[1.0, 0.0, 0.0] for _ in texts]
limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
stats = index_documents(docs, LocalStore(sys.argv[2]), mock_encoder, settings,
                        batch_size=37, stop_after_documents=limit)
print(json.dumps({"stats": stats, "encoded": len(encoded)}))
'''
        command = [sys.executable, "-c", code, str(SOURCE.parent), str(self.root)]
        first = subprocess.run([*command, "600"], capture_output=True, text=True, check=True)
        phase1 = json.loads(first.stdout)
        self.assertEqual((phase1["stats"]["documents_completed"], phase1["encoded"]), (600, 600))
        self.assertEqual(phase1["stats"]["documents_remaining"], 400)
        self.assertFalse(phase1["stats"]["complete"])
        before = {key: self.store.get(key) for key in self.store.keys()}
        second = subprocess.run(command, capture_output=True, text=True, check=True)
        phase2 = json.loads(second.stdout)
        self.assertEqual((phase2["stats"]["documents_reused"], phase2["stats"]["documents_new"],
                          phase2["stats"]["chunks_reused"], phase2["stats"]["chunks_new"],
                          phase2["encoded"]), (600, 400, 600, 400, 400))
        self.assertTrue(phase2["stats"]["complete"])
        for key, payload in before.items():
            self.assertEqual(self.store.get(key), payload)
        third = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(third.stdout)["encoded"], 0)

    def test_chunk_packing_matches_existing_paragraph_behavior(self):
        text = "one two three\n\nfour five six seven eight nine ten eleven twelve thirteen fourteen\n\nlast words"
        self.assertEqual(durable._pack(text, 10),
                         ["one two three", "four five six seven eight nine ten eleven twelve thirteen",
                          "fourteen last words"])


class S3StoreTests(unittest.TestCase):
    def store(self, client):
        return durable.S3Store("s3://test-bucket/run", endpoint_url="https://object.example.invalid", client=client)

    def test_explicit_endpoint_and_dedicated_prefix_required(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(durable.DurableError):
                durable.S3Store("s3://test-bucket/run")
        with self.assertRaises(durable.DurableError):
            durable.S3Store("s3://test-bucket", endpoint_url="https://object.example.invalid")
        with self.assertRaises(durable.DurableError):
            durable.S3Store("s3://test-bucket/run", endpoint_url="http://object.example.invalid")

    def test_environment_endpoint_and_lazy_import(self):
        with patch.dict("os.environ", {"S3_ENDPOINT_URL": "https://object.example.invalid"}):
            store = durable.S3Store("s3://test-bucket/run")
        self.assertIsNone(store._client)
        client = FakeS3()
        with patch.dict("sys.modules", {"boto3": type("Boto", (), {"client": Mock(return_value=client)})}):
            self.assertEqual(store.keys(), [])

    def test_fake_s3_complete_resume_and_paginated_listing(self):
        client = FakeS3()
        client.objects[("test-bucket", "other-prefix/untouched")] = b"preserve"
        store, docs, settings = self.store(client), documents(5), config()
        first = durable.index_documents(docs, store, MockEncoder(), settings, stop_after_documents=3)
        self.assertEqual((first["documents_completed"], first["documents_remaining"]), (3, 2))
        puts = len(client.puts)
        second = durable.index_documents(docs, store, MockEncoder(), settings)
        self.assertEqual((second["documents_reused"], second["documents_new"]), (3, 2))
        self.assertEqual(len(client.puts) - puts, 4)  # Two chunks and two document markers.
        self.assertEqual(client.objects[("test-bucket", "other-prefix/untouched")], b"preserve")
        self.assertTrue(all(prefix == "run/" for prefix in client.list_calls))
        with self.assertRaises(durable.DurableError):
            store.put_json("run.json", {"different": True})

    def test_read_after_write_failure_leaves_no_completion_marker(self):
        client = FakeS3()
        store = self.store(client)
        client.corrupt_put = True
        with self.assertRaisesRegex(durable.DurableError, "read-after-write"):
            durable.index_documents(documents(1), store, MockEncoder(), config())
        self.assertFalse(any("/documents/" in key for _, key in client.objects))


if __name__ == "__main__":
    unittest.main()
