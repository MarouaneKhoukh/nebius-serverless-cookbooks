"""Offline VM CLI integration checks; encoding/data are mocked, no GPU or cloud."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vm import cli
from vm.durable import LocalStore


class MockEncoder:
    """Deterministic unit vectors; these tests make no model-quality claims."""
    instances = []

    def __init__(self, settings, *, device):
        self.dimensions = settings["dimensions"]
        self.hardware = {"device": "offline-mock", "gpu": None, "model_load_seconds": 0.0}
        self.calls = []
        self.instances.append(self)

    def __call__(self, texts):
        self.calls.append(list(texts))
        return [[1.0] + [0.0] * (self.dimensions - 1) for _ in texts]


class ControlledExit(BaseException):
    """Stand in for os._exit without terminating the test interpreter."""


class VMCLIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = self.root / "input"
        self.data.mkdir()
        self.store = self.root / "index"
        self.runtime = json.loads((cli.ROOT / "vm/runtime.json").read_text())
        self.assertEqual(self.runtime["dimensions"], 1024)
        (self.root / "vm").mkdir()
        (self.root / "vm/runtime.json").write_text(json.dumps(self.runtime))
        brand = self.root / "docs/brand"
        brand.mkdir(parents=True)
        (brand / "nebius-logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><title>Offline fixture</title></svg>')
        self.documents = [
            {"id": "fixture-one", "title": "First fixture", "source_url": "https://example.invalid/one",
             "text": "First fixture passage with enough text to form one complete chunk."},
            {"id": "fixture-two", "title": "Second fixture", "source_url": "https://example.invalid/two",
             "text": "Second fixture passage that is separate from the first input document."},
        ]
        self.files = {
            "documents.jsonl": b'{"fixture":"documents"}\n',
            "manifest.json": b'{"fixture":"manifest"}\n',
            "LICENSE": b"Offline fixture license.\n",
            "SOURCE.md": b"Offline fixture source.\n",
        }
        for name, payload in self.files.items():
            (self.data / name).write_bytes(payload)
        MockEncoder.instances = []
        self.patches = [
            patch.object(cli, "ROOT", self.root),
            patch.object(cli, "load_documents", return_value=self.documents),
            patch.object(cli, "manifest_digest", return_value="a" * 64),
            patch("vm.model.LocalEncoder", MockEncoder),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def call(self, command, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = cli.main([command, "--data", str(self.data), "--store", str(self.store), *arguments])
        return status, stdout.getvalue(), stderr.getvalue()

    def index(self, *arguments):
        report = self.root / "last-index.json"
        status, stdout, stderr = self.call("index", *arguments, "--report", str(report))
        self.assertEqual(status, 0, stderr)
        self.last_stdout = stdout
        return json.loads(report.read_text())

    def test_index_saves_only_document_results_and_optional_local_report(self):
        result = self.index()
        self.assertTrue(result["complete"])
        self.assertEqual((result["documents_completed"], result["chunks_saved"]), (2, 2))
        keys = LocalStore(self.store).keys()
        self.assertEqual(len(keys), 3)
        self.assertTrue(all(key == "run.json" or key.startswith("documents/") for key in keys))
        self.assertFalse(Path(str(self.store) + "-measurements").exists())
        self.assertIn("0 documents already saved, 2 to go", self.last_stdout)
        self.assertIn("Finished: 2 new, 0 reused, 0 remaining", self.last_stdout)
        status, stdout, stderr = self.call("verify")
        self.assertEqual(status, 0, stderr)
        self.assertIn("All 2 documents verified", stdout)
        self.assertEqual(len(MockEncoder.instances), 1)  # Verify never loads the model.

    def test_upload_download_roundtrip_includes_all_four_input_files(self):
        object_store = self.root / "durable-inputs"
        downloaded = self.root / "downloaded"

        def validated(path):
            self.assertEqual({name: (path / name).read_bytes() for name in cli.SOURCE_FILES}, self.files)
            return self.documents

        with patch.object(cli, "load_documents", side_effect=validated) as validate, \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(cli.main(["upload-inputs", "--data", str(self.data), "--store", str(object_store)]), 0)
            self.assertEqual(cli.main(["download-inputs", "--data", str(downloaded), "--store", str(object_store)]), 0)
        self.assertIn("Uploaded 2 documents", stdout.getvalue())
        self.assertIn("Downloaded and verified 2 documents", stdout.getvalue())
        self.assertEqual({p.name for p in downloaded.iterdir()}, set(cli.SOURCE_FILES))
        self.assertEqual(set(LocalStore(object_store).keys()), set(cli.SOURCE_FILES))
        self.assertEqual({name: (downloaded / name).read_bytes() for name in cli.SOURCE_FILES}, self.files)
        self.assertEqual([item.args[0] for item in validate.call_args_list], [self.data, downloaded])
        self.assertEqual(MockEncoder.instances, [])

    def test_complete_rerun_skips_model_loading_and_embedding(self):
        self.index()
        result = self.index()
        self.assertEqual(result["documents_reused"], 2)
        self.assertEqual(result["chunks_new"], 0)
        self.assertEqual(result["model_startup_seconds"], 0.0)
        self.assertTrue(result["hardware"]["model_not_loaded"])
        self.assertEqual(len(MockEncoder.instances), 1)

    def test_upload_rejects_invalid_inputs_before_any_object_write(self):
        target = self.root / "durable-inputs"
        with patch.object(cli, "load_documents", side_effect=ValueError("fixture input checksum changed")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error:
            status = cli.main(["upload-inputs", "--data", str(self.data), "--store", str(target)])
        self.assertEqual(status, 1)
        self.assertIn("checksum changed", error.getvalue())
        self.assertEqual(LocalStore(target).keys(), [])
        self.assertEqual(MockEncoder.instances, [])

    def test_download_rejects_missing_input_or_existing_conflicting_file(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                target = self.root / ("missing-store" if missing else "complete-store")
                store = LocalStore(target)
                for name, payload in self.files.items():
                    if not missing or name != "SOURCE.md":
                        store.put(name, payload)
                downloaded = self.root / ("missing-download" if missing else "conflict-download")
                if not missing:
                    downloaded.mkdir()
                    (downloaded / "documents.jsonl").write_bytes(b"user-owned file")
                with patch.object(cli, "load_documents") as validate, \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error:
                    status = cli.main(["download-inputs", "--data", str(downloaded), "--store", str(target)])
                self.assertEqual(status, 1)
                validate.assert_not_called()
                if missing:
                    self.assertIn("Durable input is missing: SOURCE.md", error.getvalue())
                else:
                    self.assertIn("Local input differs", error.getvalue())
                    self.assertEqual((downloaded / "documents.jsonl").read_bytes(), b"user-owned file")
        self.assertEqual(MockEncoder.instances, [])

    def test_query_writes_compute_report_without_old_serverless_report(self):
        self.index()
        output = self.root / "query-output"
        with patch("embed.report", side_effect=AssertionError("do not use the old report")) as old_report:
            status, stdout, stderr = self.call(
                "query", "--text", "Find the first fixture", "--top-k", "2", "--output-dir", str(output))
        self.assertEqual(status, 0, stderr)
        old_report.assert_not_called()
        document = json.loads((output / "search.json").read_text())
        self.assertEqual(document["query"], "Find the first fixture")
        self.assertEqual(len(document["matches"]), 2)
        report = (output / "search.html").read_text()
        self.assertIn("Powered by Nebius Compute", report)
        self.assertIn("CC BY-SA 3.0", report)
        self.assertNotIn("Serverless", report)
        self.assertIn("search.html", stdout)
        query_text = MockEncoder.instances[-1].calls[0][0]
        self.assertEqual(query_text, f"Instruct: {cli.QUERY_INSTRUCTION}\nQuery:Find the first fixture")

    def test_incomplete_query_does_not_load_encoder_or_write_report(self):
        result = self.index("--max-new-documents", "1")
        self.assertFalse(result["complete"])
        MockEncoder.instances = []
        output = self.root / "query-output"
        status, stdout, stderr = self.call("query", "--text", "Find a fixture", "--output-dir", str(output))
        self.assertEqual(status, 1)
        self.assertIn("incomplete", stderr)
        self.assertEqual(MockEncoder.instances, [])
        self.assertFalse(output.exists())

    def test_same_capped_index_command_finishes_remaining_documents_on_rerun(self):
        first = self.index("--max-new-documents", "1")
        self.assertEqual((first["documents_new"], first["documents_remaining"]), (1, 1))
        second = self.index("--max-new-documents", "1")
        self.assertEqual((second["documents_reused"], second["documents_new"], second["documents_remaining"]), (1, 1, 0))
        self.assertTrue(second["complete"])
        self.assertIn("1 document already saved, 1 to go", self.last_stdout)

    def test_progress_is_brief_at_start_every_50_documents_and_finish(self):
        self.documents[:] = [
            {"id": f"fixture-{i}", "title": f"Fixture {i}",
             "source_url": f"https://example.invalid/{i}", "text": f"Distinct passage number {i}."}
            for i in range(125)]
        self.index()
        lines = self.last_stdout.splitlines()
        self.assertEqual(len(lines), 5)
        self.assertIn("0 documents already saved, 125 to go", lines[0])
        self.assertIn("50 of 125 documents saved", lines[1])
        self.assertIn("100 of 125 documents saved", lines[2])
        self.assertIn("125 of 125 documents saved", lines[3])

    def test_controlled_crash_keeps_completed_document_and_reruns_unsaved_document(self):
        # First document has one chunk; the second has three. Stop after receiving
        # the first chunk of the second document, before that document is saved.
        self.documents[1]["text"] = " ".join(["second"] * 350)
        with patch.object(cli.os, "_exit", side_effect=ControlledExit) as hard_exit, \
                contextlib.redirect_stdout(io.StringIO()) as stdout, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(ControlledExit):
            cli.main(["index", "--data", str(self.data), "--store", str(self.store),
                      "--crash-after-chunks", "2"])
        hard_exit.assert_called_once_with(75)
        self.assertIn("Controlled test stop after 2 computed chunks", stdout.getvalue())
        self.assertIn("unfinished document will run again", stdout.getvalue())
        state = cli.inspect_documents(self.documents, LocalStore(self.store), cli.run_config(self.data, self.runtime))
        self.assertEqual((state["stats"]["chunks_saved"], state["stats"]["documents_completed"]), (1, 1))
        self.assertEqual(len(LocalStore(self.store).keys()), 2)  # run + first result
        resumed = self.index()
        self.assertTrue(resumed["complete"])
        self.assertEqual((resumed["chunks_reused"], resumed["chunks_new"], resumed["documents_new"]), (1, 3, 1))
        self.assertEqual(sum(map(len, MockEncoder.instances[-1].calls)), 3)

    def test_invalid_limits_never_exit_or_start_indexing(self):
        for flag in ("--crash-after-chunks", "--max-new-documents"):
            with self.subTest(flag=flag), patch.object(cli.os, "_exit") as hard_exit, \
                    patch.object(cli, "index_documents") as index:
                status, stdout, stderr = self.call("index", flag, "0")
                self.assertEqual(status, 1)
                self.assertIn("must be positive", stderr)
                hard_exit.assert_not_called()
                index.assert_not_called()
        self.assertEqual(LocalStore(self.store).keys(), [])


if __name__ == "__main__":
    unittest.main()
