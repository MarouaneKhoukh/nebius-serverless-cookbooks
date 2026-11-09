"""Offline launcher contracts and ambiguous-write protection; never invokes Nebius."""

import argparse
import base64
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("batch_job_helper", ROOT / "scripts/job.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class JobHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        # Snapshot real injected files, so contracts and the encryption-size guard
        # are checked without creating .state files in the checkout.
        self.recipe = self.directory / "recipe"
        for relative in helper.INJECTIONS:
            destination = self.recipe / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        self.addCleanup(patch.stopall)
        patch.object(helper, "ROOT", self.recipe).start()
        patch.object(helper, "STATE", self.directory / ".state/job.json").start()
        patch.object(helper, "BUCKET_STATE", self.directory / ".state/bucket.json").start()
        patch.object(helper, "check_version").start()
        self.stdout = io.StringIO()
        self.output = redirect_stdout(self.stdout)
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.hash, self.files = helper.file_contract()

    def state(self, **changes):
        state = {
            "id": None, "name": "batch-offline-phase1", "project_id": "project-test",
            "bucket_id": "bucket-test", "bucket_name": "offline-fixture", "run_id": "backlog",
            "stop_after_batches": 2, "attempt": 1, "files_hash": self.hash, "files": self.files,
            "image": helper.IMAGE, "subnet_id": "subnet-test", "limit": 32,
            "input_key": None, "spot_pricing_policy_id": None, "previous_jobs": [],
        }
        state.update(changes)
        return state

    def args(self, **changes):
        args = argparse.Namespace(
            project_id="project-test", bucket_id="bucket-test", run_id="backlog",
            stop_after_batches=2, limit=32, input_key=None, subnet_id="subnet-test",
            spot_pricing_policy_id=None, dry_run=False, yes=True,
        )
        vars(args).update(changes)
        return args

    def job(self, state="COMPLETED"):
        return {"metadata": {"id": "aijob-fixture", "name": "batch-offline-phase1", "parent_id": "project-test"},
                "spec": {"preemptible": True, "platform": helper.PLATFORM, "preset": helper.PRESET},
                "status": {"state": state}}

    def unpack(self, payload, *, contract=None):
        destination = self.directory / "unpacked"
        source = helper.BOOTSTRAP
        anchor = 'destination = Path("/workspace/recipe")'
        self.assertEqual(source.count(anchor), 1)
        # Redirect just its hard-coded VM directory to this test's temporary
        # directory; keep verification and os.execv forwarding unchanged.
        source = source.replace(anchor, f"destination = Path({str(destination)!r})")
        argv = ["bootstrap.py", "--payload", str(payload), "--contract-hash", contract or self.hash,
                "--limit", "32", "--artifact-dir", "/data/backlog"]
        with patch.object(sys, "argv", argv), patch.dict(os.environ), patch.object(os, "execv") as execute:
            exec(compile(source, "bootstrap.py", "exec"), {"__name__": "__main__"})
            forwarded = execute.call_args
        return destination, forwarded

    def test_command_uses_offline_python_one_l40s_and_bounded_job(self):
        command = helper.command_for(self.state())
        self.assertEqual(command[:3], ["ai", "job", "create"])
        for flag, expected in {
            "--image": "vllm/vllm-openai:v0.19.1", "--platform": "gpu-l40s-d",
            "--preset": "1gpu-16vcpu-96gb", "--timeout": "1h", "--restart-policy": "never",
            "--container-command": "python3", "--working-dir": "/recipe",
            "--volume": "bucket-test:/data:rw",
        }.items():
            self.assertEqual(command[command.index(flag) + 1], expected)
        self.assertIn("--preemptible", command)
        self.assertIn("--follows-spot-price", command)
        self.assertNotIn("--spot-pricing-policy-id", command)
        self.assertFalse(any("port" in argument and argument.startswith("--") for argument in command))
        self.assertNotIn("--auth", command)
        args = command[command.index("--args") + 1]
        self.assertTrue(args.startswith("/recipe/bootstrap.py --contract-hash " + self.hash))
        self.assertIn("--config /workspace/recipe/config.json", args)
        self.assertIn("--artifact-dir /data/backlog --limit 32 --stop-after-batches 2", args)
        self.assertNotIn("api_server", args)
        self.assertNotIn("--host", args)
        injections = [command[i + 1] for i, value in enumerate(command) if value == "--inject-file"]
        self.assertEqual(len(injections), 2)
        self.assertTrue(any(item.endswith(":/recipe/payload.b64") for item in injections))
        self.assertTrue(any(item.endswith(":/recipe/bootstrap.py") for item in injections))

    def test_policy_excludes_uncapped_pricing_and_custom_key_is_forwarded(self):
        command = helper.command_for(self.state(spot_pricing_policy_id="policy-test", input_key="inputs/backlog.csv"))
        self.assertNotIn("--follows-spot-price", command)
        self.assertEqual(command[command.index("--spot-pricing-policy-id") + 1], "policy-test")
        self.assertIn("--input-file /data/inputs/backlog.csv", command[command.index("--args") + 1])

    def test_preemption_reason_is_visible_without_exposing_spec_or_ips(self):
        job = self.job("FAILED")
        job["spec"]["env"] = {"PRIVATE_TOKEN": "must-stay-private"}
        job["status"].update(state_details={"code": "Preempted"},
                             instances=[{"private_ip": "10.0.0.1"}])
        summary = helper.job_summary(job)
        self.assertEqual(summary["state"], "FAILED")
        self.assertEqual(summary["reason_code"], "Preempted")
        self.assertNotIn("must-stay-private", json.dumps(summary))
        self.assertNotIn("10.0.0.1", json.dumps(summary))

    def test_payload_manifest_matches_injected_bytes_and_executes_batch(self):
        first = helper.package_files(self.state())
        payload = first[0][0]
        encoded = payload.read_bytes()
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded, validate=True))) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            runtime = manifest["runtime"]
            self.assertEqual(hashlib.sha256(json.dumps(runtime, sort_keys=True).encode()).hexdigest(), self.hash)
            self.assertEqual(runtime["files"], self.files)
            self.assertEqual(set(archive.namelist()), {"manifest.json", *[Path(value).name for value in helper.INJECTIONS.values()]})
            self.assertNotIn("LICENSE", archive.namelist())
            for relative, info in self.files.items():
                data = archive.read(Path(info["destination"]).name)
                self.assertEqual(data, (self.recipe / relative).read_bytes())
                self.assertEqual(hashlib.sha256(data).hexdigest(), info["sha256"])
        helper.package_files(self.state())
        self.assertEqual(encoded, payload.read_bytes())
        destination, call = self.unpack(payload)
        self.assertEqual(call.args[0], sys.executable)
        self.assertEqual(call.args[1], [sys.executable, str(destination / "batch.py"), "--limit", "32", "--artifact-dir", "/data/backlog"])
        for relative, target in helper.INJECTIONS.items():
            self.assertEqual((destination / Path(target).name).read_bytes(), (self.recipe / relative).read_bytes())

    def test_bootstrap_rejects_wrong_contract_and_modified_member(self):
        payload = helper.package_files(self.state())[0][0]
        with self.assertRaisesRegex(RuntimeError, "contract"):
            self.unpack(payload, contract="0" * 64)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload.read_bytes()))) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        members["batch.py"] += b"\n# changed after contract\n"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        payload.write_bytes(base64.b64encode(stream.getvalue()))
        with self.assertRaisesRegex(RuntimeError, "checksum"):
            self.unpack(payload)

    def test_changed_recipe_cannot_be_packaged_as_same_run(self):
        path = self.recipe / "src/batch.py"
        path.write_bytes(path.read_bytes() + b"\n# a different recipe\n")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            helper.package_files(self.state())

    def test_dry_run_never_creates_or_tracks_a_job(self):
        with patch.object(helper, "cli", return_value={}) as cli:
            helper.submit_attempt(self.state(), self.args(dry_run=True))
        self.assertEqual(cli.call_count, 1)
        self.assertIn("--dry-run", cli.call_args.args[0])
        self.assertNotIn("--async", cli.call_args.args[0])
        self.assertFalse(helper.STATE.exists())

    def test_unapproved_launch_has_no_cli_mutation(self):
        with patch.object(helper, "cli") as cli:
            with self.assertRaisesRegex(RuntimeError, "--yes"):
                helper.submit_attempt(self.state(), self.args(yes=False))
        cli.assert_not_called()
        self.assertFalse(helper.STATE.exists())

    def test_repeat_submission_reuses_tracked_attempt(self):
        remote = {"job": None, "creates": 0}
        def cli(arguments, **kwargs):
            if arguments[:3] == ["ai", "job", "create"]:
                self.assertTrue(kwargs.get("mutation"))
                self.assertTrue(helper.STATE.exists())
                self.assertIsNone(helper.load_state()["id"])
                remote["creates"] += 1
                remote["job"] = self.job("RUNNING")
                return {}
            if arguments[:3] == ["ai", "job", "get-by-name"]:
                return remote["job"]
            self.fail(f"Unexpected CLI call: {arguments}")
        with patch.object(helper, "cli", side_effect=cli):
            helper.submit_attempt(self.state(), self.args())
            helper.submit_attempt(helper.load_state(), self.args())
        self.assertEqual(remote["creates"], 1)
        self.assertEqual(helper.load_state()["id"], "aijob-fixture")

    def test_ambiguous_create_is_not_blindly_repeated_and_can_be_recovered(self):
        calls = {"creates": 0, "resolved": False}
        def cli(arguments, **kwargs):
            if arguments[:3] == ["ai", "job", "create"]:
                calls["creates"] += 1
                raise RuntimeError("fixture ambiguous timeout")
            if arguments[:3] == ["ai", "job", "get-by-name"]:
                return self.job("RUNNING") if calls["resolved"] else None
            self.fail(f"Unexpected CLI call: {arguments}")
        with patch.object(helper, "cli", side_effect=cli):
            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                helper.submit_attempt(self.state(), self.args())
            self.assertIsNone(helper.load_state()["id"])
            with self.assertRaisesRegex(RuntimeError, "unresolved"):
                helper.submit_attempt(helper.load_state(), self.args())
            retry = self.args(project_id=None, bucket_id=None, run_id=None)
            with self.assertRaisesRegex(RuntimeError, "unknown"):
                helper.resume(retry)
            calls["resolved"] = True
            helper.resume(retry)
        self.assertEqual(calls["creates"], 1)
        self.assertEqual(helper.load_state()["id"], "aijob-fixture")

    def test_untracked_existing_name_does_not_attach_or_create(self):
        with patch.object(helper, "cli", return_value=self.job("RUNNING")) as cli:
            with self.assertRaisesRegex(RuntimeError, "not this tracked"):
                helper.submit_attempt(self.state(), self.args())
        self.assertEqual(cli.call_count, 1)
        self.assertFalse(helper.STATE.exists())

    def test_existing_name_requires_the_same_tracked_run_identity(self):
        previous = self.state(id="aijob-fixture")
        helper.write_state(helper.STATE, previous)
        # Different run IDs may normalize to the same lowercase/truncated name.
        # The name and code hash alone must not authorize attaching that Job.
        cases = [
            {"run_id": "Backlog"}, {"bucket_id": "bucket-different"},
            {"project_id": "project-different"}, {"limit": 64},
            {"input_key": "inputs/other.csv"},
        ]
        for changes in cases:
            state = self.state(**changes)
            remote = self.job("RUNNING")
            remote["metadata"]["parent_id"] = state["project_id"]
            with self.subTest(changes=changes), patch.object(helper, "cli", return_value=remote):
                with self.assertRaisesRegex(RuntimeError, "tracked|contract|selection|run"):
                    helper.submit_attempt(state, self.args())
        helper.write_state(helper.STATE, previous)
        remote = self.job("RUNNING")
        remote["metadata"]["id"] = "aijob-recreated"
        with patch.object(helper, "cli", return_value=remote):
            with self.assertRaisesRegex(RuntimeError, "tracked|identity|different"):
                helper.submit_attempt(self.state(), self.args())

    def test_resume_keeps_input_and_limit_and_records_previous_attempt(self):
        previous = self.state(id="aijob-fixture", input_key="inputs/backlog.csv", limit=100)
        helper.write_state(helper.STATE, previous)
        with patch.object(helper, "tracked_job", return_value=self.job()), patch.object(helper, "bucket_details"), patch.object(helper, "submit_attempt") as submit:
            helper.resume(self.args(project_id=None, bucket_id=None, run_id=None, stop_after_batches=0))
        following = submit.call_args.args[0]
        self.assertEqual(following["input_key"], previous["input_key"])
        self.assertEqual(following["limit"], 100)
        self.assertEqual(following["run_id"], previous["run_id"])
        self.assertEqual(following["stop_after_batches"], 0)
        self.assertEqual(following["attempt"], 2)
        self.assertEqual(following["name"], "batch-offline-resume-2")
        self.assertEqual(following["previous_jobs"][0]["id"], "aijob-fixture")
        self.assertIsNone(following["id"])

    def test_active_and_final_completed_jobs_are_not_resubmitted(self):
        previous = self.state(id="aijob-fixture")
        helper.write_state(helper.STATE, previous)
        args = self.args(project_id=None, bucket_id=None, run_id=None)
        with patch.object(helper, "tracked_job", return_value=self.job("RUNNING")), patch.object(helper, "submit_attempt") as submit:
            with self.assertRaisesRegex(RuntimeError, "still active"):
                helper.resume(args)
            submit.assert_not_called()
        previous["stop_after_batches"] = 0
        helper.write_state(helper.STATE, previous)
        with patch.object(helper, "tracked_job", return_value=self.job()), patch.object(helper, "submit_attempt") as submit:
            helper.resume(args)
            submit.assert_not_called()

    def test_custom_input_keys_reject_paths_and_shell_characters_before_cloud_calls(self):
        for key in ["/absolute.csv", "../escape.csv", "inputs/../escape.csv", "inputs//file.csv", "inputs/file name.csv", "inputs/a;echo.csv", "https://host/input.csv", "inputs/$(cmd).csv", "inputs/a\\b.csv"]:
            with self.subTest(key=key), patch.object(helper, "bucket_details") as bucket, patch.object(helper, "submit_attempt") as submit:
                with self.assertRaisesRegex(RuntimeError, "safe object key"):
                    helper.submit(self.args(input_key=key))
                bucket.assert_not_called()
                submit.assert_not_called()
        with patch.object(helper, "bucket_details", return_value={"metadata": {"name": "fixture"}}), patch.object(helper, "submit_attempt") as submit:
            helper.submit(self.args(input_key="inputs/backlog-2026.v2.csv"))
        self.assertEqual(submit.call_args.args[0]["input_key"], "inputs/backlog-2026.v2.csv")

    def test_resume_rejects_project_bucket_or_run_changes(self):
        helper.write_state(helper.STATE, self.state(id="aijob-fixture"))
        for field in ["project_id", "bucket_id", "run_id"]:
            args = self.args(project_id=None, bucket_id=None, run_id=None)
            setattr(args, field, "different")
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "same " + field):
                helper.resume(args)


if __name__ == "__main__":
    unittest.main()
