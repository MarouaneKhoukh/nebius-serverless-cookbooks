"""Offline safety/recovery checks. These do not establish real model quality."""

import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from runner import Endpoint, RecipeError, load_rows, normalize_label, read_json, render_report, run_rows, safe_base_url, settings_for


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.rows = [{"id": str(i), "prompt": f"Request {i}"} for i in range(3)]

    def tearDown(self):
        self.temporary.cleanup()

    def write_input(self, text):
        path = self.directory / "input.csv"
        path.write_text(text)
        return path

    def test_csv_rejects_duplicate_missing_and_malformed_rows(self):
        for text in ("id,prompt\na,hello\na,world\n", "id,prompt\na,\n", "prompt\nhello\n", "id,prompt\na,hello,extra\n", "id,prompt\n"):
            with self.subTest(text=text), self.assertRaises(RecipeError):
                load_rows(self.write_input(text))

    def test_csv_accepts_quoted_multiline_prompt(self):
        rows = load_rows(self.write_input('id,prompt\na,"Hello, world\nSecond line"\n'))
        self.assertEqual(rows[0]["prompt"], "Hello, world\nSecond line")

    def test_interrupted_run_resumes_only_missing_rows(self):
        calls = []
        def complete(prompt, settings):
            calls.append(prompt)
            if len(calls) == 3:
                raise RecipeError("interrupted")
            return {"response": "billing", "label": "billing"}
        with self.assertRaises(RecipeError):
            run_rows(self.rows, self.directory, settings_for(), complete)
        self.assertEqual(len(list((self.directory / "items").glob("*.json"))), 2)
        records = run_rows(self.rows, self.directory, settings_for(), complete)
        self.assertEqual(len(records), 3)
        self.assertEqual(calls, ["Request 0", "Request 1", "Request 2", "Request 2"])

    def test_new_model_or_input_cannot_reuse_old_predictions(self):
        def complete(prompt, settings):
            return {"response": "billing", "label": "billing"}
        run_rows(self.rows, self.directory, settings_for(), complete, limit=1)
        for rows, settings in (([{**self.rows[0], "prompt": "Changed"}], settings_for()), (self.rows, settings_for("another/model"))):
            with self.subTest(settings=settings), self.assertRaisesRegex(RecipeError, "changed"):
                run_rows(rows, self.directory, settings, complete)

    def test_corrupt_completed_file_is_not_silently_overwritten(self):
        run_rows(self.rows, self.directory, settings_for(), lambda *args: {"response": "billing", "label": "billing"}, limit=1)
        path = next((self.directory / "items").glob("*.json"))
        path.write_text("broken")
        with self.assertRaises(RecipeError):
            run_rows(self.rows, self.directory, settings_for(), lambda *args: self.fail("must not call model"))
        self.assertEqual(path.read_text(), "broken")

    def test_labels_do_not_accept_explanations_or_multiple_answers(self):
        self.assertEqual(normalize_label(' "Billing" '), "billing")
        self.assertEqual(normalize_label('"billing".'), "billing")
        self.assertEqual(normalize_label("technical."), "technical")
        for response in ("billing or account", "This is billing", "", "<script>alert(1)</script>"):
            self.assertIsNone(normalize_label(response))

    def test_credentials_cannot_be_embedded_in_url(self):
        for url in ("https://secret@example.com", "https://example.com?token=secret", "http://example.com"):
            with self.assertRaises(RecipeError):
                safe_base_url(url)
        self.assertEqual(safe_base_url("https://example.com/v1/"), "https://example.com")

    def test_auth_failure_is_not_retried_or_echoed(self):
        endpoint = Endpoint("https://example.com", "SECRET_VALUE")
        error = urllib.error.HTTPError("https://example.com", 401, "Unauthorized", {}, io.BytesIO(b"SECRET_VALUE"))
        with patch("urllib.request.urlopen", side_effect=error) as request:
            with self.assertRaises(RecipeError) as raised:
                endpoint.complete("hello", settings_for())
        self.assertEqual(request.call_count, 1)
        self.assertNotIn("SECRET_VALUE", str(raised.exception))

    def test_transient_failure_retries_then_returns_result(self):
        endpoint = Endpoint("https://example.com", "SECRET_VALUE", attempts=2)
        error = urllib.error.HTTPError("https://example.com", 503, "Unavailable", {}, io.BytesIO())
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "account"}}]}).encode())
        with patch("urllib.request.urlopen", side_effect=[error, response]) as request, patch("time.sleep"):
            result = endpoint.complete("hello", settings_for())
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["label"], "account")

    def test_empty_model_response_is_not_a_completed_prediction(self):
        endpoint = Endpoint("https://example.com", "SECRET_VALUE")
        with patch.object(endpoint, "request", return_value={"choices": [{"message": {"content": ""}}]}):
            with self.assertRaises(RecipeError):
                endpoint.complete("hello", settings_for())

    def test_report_escapes_untrusted_input(self):
        report = self.directory / "report.html"
        render_report(report, "A report", "Saved results", ["response"], [{"response": "<script>alert('bad')</script>"}])
        text = report.read_text()
        self.assertIn("Powered by Nebius Serverless AI", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>", text)


if __name__ == "__main__":
    unittest.main()
