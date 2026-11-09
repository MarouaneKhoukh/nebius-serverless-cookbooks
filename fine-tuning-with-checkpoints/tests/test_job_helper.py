"""Offline checks for the launcher; no Nebius requests or resources are created."""
import argparse
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts/job.py"
SPEC = importlib.util.spec_from_file_location("recipe_job", MODULE)
job = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(job)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "config/train.yaml").write_text("save_steps: 10\nmax_steps: 30\n")
        (self.root / "input.jsonl").write_text('{"example":1}\n')
        (self.root / "train.py").write_text('print("fixture training entrypoint")\n')
        self.patches = [patch.object(job, "ROOT", self.root),
                        patch.object(job, "STATE", self.root / ".state/job.json"),
                        patch.object(job, "INJECTIONS", {"config/train.yaml": "/recipe/train.yaml", "input.jsonl": "/recipe/train.jsonl", "train.py": "/recipe/train.py"})]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def state(self):
        aggregate, files = job.file_contract()
        return {"id": "aijob-test", "name": "ft-example-hash-phase1", "project_id": "project-test",
                "bucket_id": "bucket-test", "bucket_name": "sample-bucket", "run_id": "example", "stop_after_step": 10,
                "attempt": 1, "files_hash": aggregate, "files": files, "image": job.IMAGE,
                "subnet_id": "vpcsubnet-test", "spot_pricing_policy_id": None, "previous_jobs": []}

    def test_command_keeps_spot_timeout_and_separate_runtime_args(self):
        command = job.command_for(self.state())
        self.assertIn("--preemptible", command)
        self.assertIn("--follows-spot-price", command)
        self.assertEqual(command[command.index("--timeout") + 1], "1h")
        self.assertEqual(command[command.index("--restart-policy") + 1], "never")
        runtime_args = command[command.index("--args") + 1]
        self.assertTrue(runtime_args.startswith("/recipe/bootstrap.py --contract-hash "))
        self.assertTrue(runtime_args.endswith("--artifact-dir /data/example --stop-after-step 10"))
        self.assertEqual(command.count("--inject-file"), 2)
        self.assertEqual(command[command.index("--subnet-id") + 1], "vpcsubnet-test")

    def test_changed_input_changes_resume_contract_and_oversized_input_fails(self):
        original, _ = job.file_contract()
        (self.root / "input.jsonl").write_text('{"example":2}\n')
        changed, _ = job.file_contract()
        self.assertNotEqual(original, changed)
        (self.root / "input.jsonl").write_bytes(b"x" * (64 * 1024 + 1))
        with self.assertRaisesRegex(RuntimeError, "64 KiB"):
            job.file_contract()

    def test_resume_creates_new_attempt_with_same_contract_and_zero_stop(self):
        state = self.state()
        job.write_state(job.STATE, state)
        args = argparse.Namespace(project_id=None, bucket_id=None, run_id=None, subnet_id=None,
                                  spot_pricing_policy_id=None, yes=True, dry_run=False)
        observed = []
        with patch.object(job, "check_version"), \
             patch.object(job, "tracked_job", return_value={"status": {"state": "COMPLETED"}}), \
             patch.object(job, "bucket_details"), \
             patch.object(job, "submit_attempt", side_effect=lambda value, args: observed.append(value)):
            job.resume(args)
        resumed = observed[0]
        self.assertEqual(resumed["run_id"], state["run_id"])
        self.assertEqual(resumed["bucket_id"], state["bucket_id"])
        self.assertEqual(resumed["files_hash"], state["files_hash"])
        self.assertEqual(resumed["subnet_id"], state["subnet_id"])
        self.assertEqual(resumed["stop_after_step"], 0)
        self.assertEqual(resumed["attempt"], 2)
        self.assertIsNone(resumed["id"])
        self.assertNotEqual(resumed["name"], state["name"])

    def test_resume_refuses_changed_recipe_before_submitting(self):
        job.write_state(job.STATE, self.state())
        (self.root / "input.jsonl").write_text('{"changed":true}\n')
        args = argparse.Namespace(project_id=None, bucket_id=None, run_id=None)
        with patch.object(job, "check_version"), patch.object(job, "submit_attempt") as submit:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                job.resume(args)
            submit.assert_not_called()

    def test_ambiguous_submission_is_not_repeated(self):
        state = self.state()
        state["id"] = None
        job.write_state(job.STATE, state)
        args = argparse.Namespace(dry_run=False, yes=True)
        with patch.object(job, "cli", return_value=None) as cli, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "unresolved"):
                job.submit_attempt(state, args)
        self.assertEqual(cli.call_count, 1)
        self.assertEqual(cli.call_args.args[0][:3], ["ai", "job", "get-by-name"])

    def test_not_found_is_distinct_from_network_failure(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "rpc error: code = NotFound desc = absent")):
            self.assertIsNone(job.cli(["ai", "job", "get-by-name"], allow_not_found=True))
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "lookup api.example: host not found")):
            with self.assertRaisesRegex(RuntimeError, "host not found"):
                job.cli(["ai", "job", "get-by-name"], allow_not_found=True)

    def test_successful_plain_text_dry_run_is_accepted(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "Dry run: request validated.\n", "")):
            self.assertEqual(job.cli(["ai", "job", "create", "--dry-run"]), {})
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "invalid preset")):
            with self.assertRaisesRegex(RuntimeError, "invalid preset"):
                job.cli(["ai", "job", "create", "--dry-run"])

    def test_untracked_job_id_and_wrong_project_are_rejected(self):
        state = self.state()
        with self.assertRaisesRegex(RuntimeError, "only manages"):
            job.tracked_job(state, "aijob-unrelated")
        with patch.object(job, "cli", return_value={"metadata": {"parent_id": "project-other"}}):
            with self.assertRaisesRegex(RuntimeError, "different project"):
                job.tracked_job(state)

    def test_stop_boundary_and_secret_redaction(self):
        for step in (10, 20, 0):
            job.validate_stop(step)
        for step in (5, 30, -1):
            with self.assertRaises(RuntimeError):
                job.validate_stop(step)
        self.assertNotIn("my-value", job.scrub("Authorization: Bearer my-value"))
        self.assertNotIn("hf_1234567890123456", job.scrub("hf_1234567890123456"))

    def test_packaged_bytes_are_deterministic_and_original_files_match(self):
        state = self.state()
        sources = job.package_files(state)
        first = sources[0][0].read_bytes()
        job.package_files(state)
        self.assertEqual(first, sources[0][0].read_bytes())
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(first, validate=True))) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["runtime"]["files"], state["files"])
            for relative, destination in job.INJECTIONS.items():
                self.assertEqual(archive.read(Path(destination).name), (self.root / relative).read_bytes())

    def test_total_encoded_injection_limit_is_checked_before_submission(self):
        # Individually below 64 KiB, but too large after ZIP/base64/KMS serialization.
        import os
        (self.root / "input.jsonl").write_bytes(os.urandom(44000))
        state = self.state()
        with self.assertRaisesRegex(RuntimeError, "Move larger datasets"):
            job.package_files(state)

    def run_bootstrap(self, state, payload):
        destination = self.root / "expanded"
        source = job.BOOTSTRAP.replace('Path("/workspace/recipe")', f"Path({str(destination)!r})")
        args = ["bootstrap.py", "--contract-hash", state["files_hash"], "--payload", str(payload),
                "--artifact-dir", "/data/example", "--stop-after-step", "10"]
        with patch("sys.argv", args), patch("os.execv") as execute, patch.dict("os.environ", {}, clear=False):
            exec(compile(source, "bootstrap.py", "exec"), {})
        return destination, execute

    def test_bootstrap_verifies_and_expands_then_preserves_training_arguments(self):
        state = self.state()
        payload = job.package_files(state)[0][0]
        destination, execute = self.run_bootstrap(state, payload)
        self.assertEqual((destination / "train.jsonl").read_bytes(), (self.root / "input.jsonl").read_bytes())
        self.assertEqual(execute.call_args.args[1][1:], [str(destination / "train.py"), "--artifact-dir", "/data/example", "--stop-after-step", "10"])

    def test_bootstrap_rejects_traversal_and_corrupt_recipe_content(self):
        state = self.state()
        payload = job.package_files(state)[0][0]
        original = base64.b64decode(payload.read_bytes(), validate=True)
        for malicious in (True, False):
            data = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(data, "w") as archive:
                for name in source.namelist():
                    content = source.read(name)
                    if not malicious and name == "train.jsonl":
                        content += b"corrupted"
                    archive.writestr(name, content)
                if malicious:
                    archive.writestr("../escape.py", b"unsafe")
            payload.write_bytes(base64.b64encode(data.getvalue()))
            with self.assertRaisesRegex(RuntimeError, "flat filenames|checksum mismatch"):
                self.run_bootstrap(state, payload)


if __name__ == "__main__":
    unittest.main()
