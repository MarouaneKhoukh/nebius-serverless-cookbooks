"""Offline data integrity/recovery tests, separate from actual model validation."""

import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from embed import Endpoint, MODEL, QUERY_INSTRUCTION, RecipeError, index_collection, load_chunks, query_collection, read_json, report, unit_vector


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.documents = self.root / "documents"
        self.documents.mkdir()
        for number in range(6):
            (self.documents / f"document-{number}.txt").write_text(f"Document number {number}. " + "A useful passage with some content. " * 3)
        self.chunks = load_chunks(self.documents)
        self.output = self.root / "results"
        self.settings = {"model": MODEL, "model_revision": "test-only", "dimensions": 32, "chunk_words": 160}
        self.vector = [1.0] + [0.0] * 31

    def tearDown(self):
        self.temporary.cleanup()

    def test_bundled_documents_have_stable_distinct_chunk_ids(self):
        directory = Path(__file__).resolve().parents[1] / "data" / "documents"
        chunks = load_chunks(directory)
        self.assertEqual(len(chunks), 6)
        self.assertEqual(chunks, load_chunks(directory))
        self.assertEqual(len({chunk["id"] for chunk in chunks}), len(chunks))

    def test_chunking_preserves_all_words_and_respects_size(self):
        (self.documents / "long.txt").write_text(" ".join("word" + str(i) for i in range(53)))
        chunks = [chunk for chunk in load_chunks(self.documents, 10) if chunk["source"] == "long.txt"]
        self.assertEqual([len(chunk["text"].split()) for chunk in chunks], [10, 10, 10, 10, 10, 3])
        self.assertEqual(" ".join(chunk["text"] for chunk in chunks), " ".join("word" + str(i) for i in range(53)))

    def test_invalid_vectors_are_rejected(self):
        for vector in ([0.0] * 32, [1.0] * 31, [True] * 32, [float("nan")] * 32, [float("inf")] * 32):
            with self.subTest(vector=vector[:2]), self.assertRaises(RecipeError):
                unit_vector(vector, 32)

    def test_api_reorders_valid_vectors_by_response_index(self):
        endpoint = Endpoint("https://example.com", "secret")
        first = [1.0] + [0.0] * 1023
        other = [0.0, 1.0] + [0.0] * 1022
        with patch.object(endpoint, "request", return_value={"data": [{"index": 1, "embedding": other}, {"index": 0, "embedding": first}]}) as request:
            vectors = endpoint.embed(["first", "second"], MODEL, 1024)
            self.assertEqual(vectors, [first, other])
            self.assertEqual(len(vectors[0]), 1024)
            self.assertNotIn("dimensions", request.call_args.args[1])
            self.assertEqual(request.call_args.args[1]["encoding_format"], "float")

    def test_api_rejects_missing_duplicate_or_invalid_embedding(self):
        endpoint = Endpoint("https://example.com", "secret")
        vector = [1.0] + [0.0] * 1023
        responses = [
            {"data": [{"index": 0, "embedding": vector}]},
            {"data": [{"index": 0, "embedding": vector}, {"index": 0, "embedding": vector}]},
            {"data": [{"index": 0, "embedding": vector}, {"index": 1, "embedding": [float("nan")] * 1024}]},
            {"data": [{"index": 0, "embedding": vector}, {"index": 1, "embedding": self.vector}]},
        ]
        for response in responses:
            with self.subTest(response=response), patch.object(endpoint, "request", return_value=response), self.assertRaises(RecipeError):
                endpoint.embed(["a", "b"], MODEL, 1024)

    def test_failed_batch_is_not_marked_saved_and_resume_skips_completed(self):
        calls = []
        def embed(texts, model, dimensions):
            calls.append(texts)
            if len(calls) == 2:
                raise RecipeError("Endpoint interrupted")
            return [self.vector for text in texts]
        with self.assertRaises(RecipeError):
            index_collection(self.chunks, self.output, self.settings, embed)
        manifest = read_json(self.output / "manifest.json")
        self.assertFalse(manifest["complete"])
        self.assertEqual(manifest["chunks_saved"], 2)
        result = index_collection(self.chunks, self.output, self.settings, embed)
        self.assertTrue(result["complete"])
        self.assertEqual(len(calls), 4)
        resumed_texts = [text for batch in calls[2:] for text in batch]
        self.assertNotIn(self.chunks[0]["text"], resumed_texts)
        self.assertNotIn(self.chunks[1]["text"], resumed_texts)

    def test_changed_input_or_dimensions_cannot_reuse_vectors(self):
        def embed(*args):
            return [self.vector] * len(args[0])
        index_collection(self.chunks, self.output, self.settings, embed, limit=2)
        for chunks, settings in ((self.chunks, {**self.settings, "dimensions": 64}), (self.chunks[:-1], self.settings)):
            with self.subTest(settings=settings), self.assertRaisesRegex(RecipeError, "changed"):
                index_collection(chunks, self.output, settings, lambda *args: self.fail("must not request more vectors"))

    def test_vectors_and_metadata_have_matching_ids(self):
        index_collection(self.chunks, self.output, self.settings, lambda texts, *args: [self.vector] * len(texts))
        vectors = [json.loads(line) for line in (self.output / "vectors.jsonl").read_text().splitlines()]
        metadata = [json.loads(line) for line in (self.output / "metadata.jsonl").read_text().splitlines()]
        self.assertEqual([record["id"] for record in vectors], [record["id"] for record in metadata])
        self.assertTrue(all(len(record["vector"]) == 32 for record in vectors))

    def test_query_embeds_only_the_instructed_query(self):
        index_collection(self.chunks, self.output, self.settings, lambda texts, *args: [self.vector] * len(texts))
        calls = []
        class QueryEndpoint:
            def ready(self, model):
                self.model = model
            def embed(inner, texts, model, dimensions):
                calls.append(texts)
                return [self.vector]
        results = query_collection(self.output, "Where is my invoice?", QueryEndpoint())
        self.assertEqual(calls, [["Instruct: " + QUERY_INSTRUCTION + "\nQuery:Where is my invoice?"]])
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["similarity"], 1.0)

    def test_partial_index_cannot_be_queried_as_complete(self):
        index_collection(self.chunks, self.output, self.settings, lambda texts, *args: [self.vector] * len(texts), limit=2)
        with self.assertRaisesRegex(RecipeError, "incomplete"):
            query_collection(self.output, "A query", None)

    def test_invalid_batch_does_not_save_any_of_its_rows(self):
        with self.assertRaises(RecipeError):
            index_collection(self.chunks, self.output, self.settings, lambda *args: [self.vector, [0.0] * 32])
        self.assertEqual(read_json(self.output / "manifest.json")["chunks_saved"], 0)

    def test_auth_error_is_redacted_and_not_retried(self):
        endpoint = Endpoint("https://example.com", "SECRET_VALUE")
        error = urllib.error.HTTPError("https://example.com", 401, "Unauthorized", {}, io.BytesIO(b"SECRET_VALUE"))
        with patch("urllib.request.urlopen", side_effect=error) as request, self.assertRaises(RecipeError) as raised:
            endpoint.embed(["text"], MODEL, 1024)
        self.assertEqual(request.call_count, 1)
        self.assertNotIn("SECRET_VALUE", str(raised.exception))

    def test_report_escapes_documents_and_query(self):
        output = self.root / "report.html"
        report(output, "<script>title</script>", "<img onerror=bad>", ["text"], [{"text": "<script>bad</script>"}])
        rendered = output.read_text()
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("Powered by Nebius Serverless AI", rendered)


if __name__ == "__main__":
    unittest.main()
