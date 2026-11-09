#!/usr/bin/env python3
"""Launch and resume this Axolotl recipe on Spot without exposing credentials."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".state" / "job.json"
BUCKET_STATE = ROOT / ".state" / "bucket.json"
CLI = os.environ.get("NEBIUS_BIN", "nebius")
IMAGE = "docker.io/axolotlai/axolotl:main-20260309-py3.11-cu128-2.9.1"
PLATFORM, PRESET = "gpu-h100-sxm", "1gpu-16vcpu-200gb"
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "CANCELED", "ERROR", "DELETED"}
INJECTIONS = {
    "src/train.py": "/recipe/train.py",
    "src/checkpoint_store.py": "/recipe/checkpoint_store.py",
    "src/spot_checkpoint_plugin.py": "/recipe/spot_checkpoint_plugin.py",
    "src/evaluate.py": "/recipe/evaluate.py",
    "config/train.yaml": "/recipe/train.yaml",
    "src/banking77.py": "/recipe/banking77.py",
    "src/data_prep.py": "/recipe/data_prep.py",
    "config/data.json": "/recipe/data.json",
    "data/categories.json": "/recipe/categories.json",
    "data/SOURCE.md": "/recipe/SOURCE.md",
    "docs/brand/nebius-logo.svg": "/recipe/nebius-logo.svg",
}

# This code expands only the bundled recipe files, on VM-local storage.
# It does not download code or write checkpoints to the bucket itself.
BOOTSTRAP = r'''import argparse, base64, hashlib, io, json, os, re, sys, zipfile
from pathlib import Path

p = argparse.ArgumentParser(description="Verify and unpack the cookbook payload")
p.add_argument("--contract-hash", required=True)
p.add_argument("--payload", default="/recipe/payload.b64")
args, train_args = p.parse_known_args()
data = base64.b64decode(Path(args.payload).read_bytes(), validate=True)
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    names = archive.namelist()
    if len(names) != len(set(names)) or "manifest.json" not in names:
        raise RuntimeError("Invalid or duplicate payload members")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) for name in names):
        raise RuntimeError("Payload paths must be flat filenames")
    if any(item.file_size > 65536 for item in archive.infolist()):
        raise RuntimeError("Unexpected oversized payload member")
    manifest = json.loads(archive.read("manifest.json"))
    runtime = manifest["runtime"]
    actual_contract = hashlib.sha256(json.dumps(runtime, sort_keys=True).encode()).hexdigest()
    if manifest.get("schema") != 1 or actual_contract != args.contract_hash:
        raise RuntimeError("Payload contract does not match the submitted recipe")
    files = runtime["files"]
    targets = [Path(info["destination"]).name for info in files.values()]
    if len(targets) != len(set(targets)) or set(names) != {"manifest.json", *targets} or "train.py" not in targets:
        raise RuntimeError("Payload member list differs from the manifest")
    destination = Path("/workspace/recipe")
    destination.mkdir(parents=True, exist_ok=True)
    for info in files.values():
        name = Path(info["destination"]).name
        content = archive.read(name)
        if hashlib.sha256(content).hexdigest() != info["sha256"]:
            raise RuntimeError("Recipe file checksum mismatch: " + name)
        temporary = destination / (name + ".part")
        temporary.write_bytes(content)
        temporary.replace(destination / name)
os.environ["PYTHONPATH"] = str(destination) + os.pathsep + os.environ.get("PYTHONPATH", "")
os.execv(sys.executable, [sys.executable, str(destination / "train.py"), *train_args])
'''


def scrub(text):
    """Keep diagnostics useful while suppressing common credential formats."""
    text = re.sub(r"(?is)-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[redacted private key]", text)
    text = re.sub(r"(?i)\bBearer\s+[^\s,;\"']+", "Bearer [redacted]", text)
    text = re.sub(r"\bhf_[A-Za-z0-9]{12,}\b", "[redacted Hugging Face token]", text)
    text = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[redacted access key]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[redacted JWT]", text)
    text = re.sub(r"(?im)^.*(?:auth_token|access_token|secret_access_key|authorization|password)\s*[=:].*$", "[redacted credential line]", text)
    return text


def cli(args, *, allow_not_found=False, mutation=False, text=False):
    command = [CLI, *args, "--no-progress", "--no-browser"]
    if not text:
        command += ["--format", "json"]
    if mutation:
        command += ["--retries", "1"]  # Never silently retry an ambiguous write.
    env = {**os.environ, "AI_AGENT": os.environ.get("AI_AGENT") or "cookbook"}
    try:
        proc = subprocess.run(command, capture_output=True, text=True, env=env, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Nebius CLI did not finish. Inspect the resource by name before retrying a mutation.") from exc
    if proc.returncode:
        # Match API NotFound codes, not a generic DNS/network 'not found' message.
        if allow_not_found and re.search(r"\b(?:NotFound|NOT_FOUND)\b|\"code\"\s*:\s*404\b", proc.stderr):
            return None
        diagnostic = scrub(proc.stderr).strip()
        raise RuntimeError(diagnostic[:1800] or "Nebius request failed. Check sign-in, project, quota and CLI version.")
    if text:
        return scrub(proc.stdout)
    if "--dry-run" in args:
        # Static create validation prints a human confirmation even with --format json.
        # Exit status is authoritative; no resource or credential output is needed.
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Nebius returned unexpected output; inspect state in the console before retrying a write.") from exc


def check_version():
    env = {**os.environ, "AI_AGENT": os.environ.get("AI_AGENT") or "cookbook"}
    proc = subprocess.run([CLI, "version"], capture_output=True, text=True, env=env, timeout=30)
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", proc.stdout)
    if proc.returncode or not match or tuple(map(int, match.groups())) < (0, 12, 303):
        raise RuntimeError("Install/update Nebius CLI to 0.12.303 or newer; this recipe needs the current Spot pricing flags.")


def write_state(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_state():
    if not STATE.is_file():
        raise RuntimeError("No Job is tracked. Run submit first.")
    return json.loads(STATE.read_text(encoding="utf-8"))


def validate_id(value, kind):
    if not value or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]+", value):
        raise RuntimeError(f"Use a valid {kind} ID, without paths or spaces.")
    if kind == "project" and not value.startswith("project-"):
        raise RuntimeError("Select a project ID beginning with project-.")
    return value


def validate_run_id(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value or ""):
        raise RuntimeError("Run ID must be 1–64 filename-safe characters; no slashes or spaces.")
    return value


def file_contract():
    files = {}
    for relative, destination in INJECTIONS.items():
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"Missing required recipe file: {relative}")
        data = path.read_bytes()
        if len(data) > 64 * 1024:
            raise RuntimeError(f"{relative} exceeds Nebius's 64 KiB injected-file limit; move larger datasets to storage.")
        files[relative] = {"sha256": hashlib.sha256(data).hexdigest(), "destination": destination}
    runtime = {"image": IMAGE, "platform": PLATFORM, "preset": PRESET, "files": files}
    aggregate = hashlib.sha256(json.dumps(runtime, sort_keys=True).encode()).hexdigest()
    return aggregate, files


def package_files(state):
    """Prepare deterministic compressed files under the total encrypted-file limit."""
    aggregate, files = file_contract()
    if aggregate != state["files_hash"]:
        raise RuntimeError("Recipe files changed after the run contract was recorded; use the original files or a new run ID.")
    runtime = {"image": IMAGE, "platform": PLATFORM, "preset": PRESET, "files": files}
    members = {Path(value["destination"]).name: (ROOT / relative).read_bytes()
               for relative, value in files.items()}
    if len(members) != len(files):
        raise RuntimeError("Recipe payload has duplicate destination filenames.")
    members["manifest.json"] = json.dumps({"schema": 1, "runtime": runtime}, sort_keys=True).encode()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, members[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    payload = base64.b64encode(archive_bytes.getvalue())
    bootstrap = BOOTSTRAP.encode("utf-8")
    # The CLI serializes injected file bytes as base64 again before KMS encryption.
    # Leave room for JSON keys/paths and provider metadata below its 64 KiB limit.
    raw_total = len(payload) + len(bootstrap)
    encrypted_plaintext_estimate = ((raw_total + 2) // 3) * 4 + 4096
    if encrypted_plaintext_estimate > 60 * 1024:
        raise RuntimeError(
            f"Compressed injected recipe is too large (estimated {encrypted_plaintext_estimate} bytes including encoding/metadata; limit 60 KiB). "
            "Move larger datasets/artifacts to Object Storage instead of injecting them."
        )
    directory = STATE.parent
    directory.mkdir(parents=True, exist_ok=True)
    payload_path, bootstrap_path = directory / "recipe-payload.b64", directory / "bootstrap.py"
    payload_path.write_bytes(payload)
    bootstrap_path.write_bytes(bootstrap)
    return [(payload_path, "/recipe/payload.b64"), (bootstrap_path, "/recipe/bootstrap.py")]


def validate_stop(step):
    config = (ROOT / "config/train.yaml").read_text(encoding="utf-8")
    values = {}
    for name in ("save_steps", "max_steps"):
        match = re.search(rf"(?m)^{name}:\s*(\d+)\s*$", config)
        if not match or int(match.group(1)) < 1:
            raise RuntimeError(f"config/train.yaml must declare a positive integer {name}.")
        values[name] = int(match.group(1))
    if step < 0 or (step and (step % values["save_steps"] or step >= values["max_steps"])):
        raise RuntimeError("Controlled stop must be 0, or a save-step boundary below max_steps.")


def bucket_details(project, bucket_id):
    bucket = cli(["storage", "bucket", "get", "--id", validate_id(bucket_id, "bucket")])
    if bucket.get("metadata", {}).get("parent_id") != project:
        raise RuntimeError("Bucket does not belong to the selected project. Use a bucket in the Job's project/region.")
    return bucket


def job_summary(job):
    metadata, spec, status = job.get("metadata", {}), job.get("spec", {}), job.get("status", {})
    return {"id": metadata.get("id"), "name": metadata.get("name"),
            "project_id": metadata.get("parent_id"), "state": status.get("state"),
            "reason_code": status.get("state_details", {}).get("code"),
            "spot": spec.get("preemptible", False), "platform": spec.get("platform"),
            "preset": spec.get("preset")}


def tracked_job(state, job_id=None):
    selected = job_id or state.get("id")
    known = {state.get("id"), *(item.get("id") for item in state.get("previous_jobs", []))}
    if job_id and job_id not in known:
        raise RuntimeError("This helper only manages Job IDs recorded in .state/job.json.")
    if selected:
        job = cli(["ai", "job", "get", "--id", selected])
    else:
        job = cli(["ai", "job", "get-by-name", "--parent-id", state["project_id"], "--name", state["name"]], allow_not_found=True)
        if not job:
            raise RuntimeError("Submission outcome is still unknown. Check the Job name in the console; do not blindly submit again.")
    if job.get("metadata", {}).get("parent_id") != state["project_id"]:
        raise RuntimeError("Job belongs to a different project; no action was taken.")
    if not selected:
        state["id"] = job["metadata"]["id"]
        write_state(STATE, state)
    return job


def create_bucket(args):
    check_version()
    project = validate_id(args.project_id, "project")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", args.name):
        raise RuntimeError("Use a 3–63 character lowercase bucket name with letters, numbers, dots or hyphens.")
    existing = cli(["storage", "bucket", "get-by-name", "--parent-id", project, "--name", args.name], allow_not_found=True)
    if existing:
        bucket = existing
        print("Using the existing bucket with this name; no new bucket was created.")
    else:
        command = ["storage", "bucket", "create", "--parent-id", project, "--name", args.name,
                   "--max-size-bytes", str(10 * 1024**3)]
        print(shlex.join([CLI, *command]))
        print("Creates private Object Storage with a 10 GiB size limit. Stored artifacts remain billable until removed; this does not launch a GPU.")
        if not args.yes:
            raise RuntimeError("Review the bucket/project, then add --yes to create it.")
        cli(command, mutation=True)
        bucket = cli(["storage", "bucket", "get-by-name", "--parent-id", project, "--name", args.name])
    metadata = bucket.get("metadata", {})
    if metadata.get("parent_id") != project or not metadata.get("id"):
        raise RuntimeError("Returned bucket does not match the selected project.")
    info = {"id": metadata["id"], "name": metadata.get("name"), "project_id": project}
    write_state(BUCKET_STATE, info)
    print(json.dumps(info, indent=2))


def command_for(state):
    packaged = package_files(state)
    command = ["ai", "job", "create", "--parent-id", state["project_id"], "--name", state["name"],
               "--image", IMAGE, "--platform", PLATFORM, "--preset", PRESET,
               "--preemptible", "--disk-size", "500Gi", "--shm-size", "16Gi",
               "--timeout", "1h", "--restart-policy", "never", "--working-dir", "/recipe",
               "--container-command", "python3", "--args",
               f"/recipe/bootstrap.py --contract-hash {state['files_hash']} --artifact-dir /data/{state['run_id']} --stop-after-step {state['stop_after_step']}",
               "--volume", state["bucket_id"] + ":/data:rw",
               "--env", "ARTIFACT_DIR=/data/" + state["run_id"],
               "--env", "STOP_AFTER_STEP=" + str(state["stop_after_step"]),
               "--env", "PYTHONPATH=/recipe", "--env", "PYTHONDONTWRITEBYTECODE=1"]
    command += (["--spot-pricing-policy-id", state["spot_pricing_policy_id"]]
                if state.get("spot_pricing_policy_id") else ["--follows-spot-price"])
    if state.get("subnet_id"):
        command += ["--subnet-id", state["subnet_id"]]
    for source, destination in packaged:
        command += ["--inject-file", str(source) + ":" + destination]
    return command


def submit_attempt(state, args):
    command = command_for(state)
    print(shlex.join([CLI, *command, "--dry-run" if args.dry_run else "--async"]))
    print("One preemptible H100, with a 1-hour Job timeout. Model loading counts toward paid time. "
          + ("The selected Spot policy caps the hourly price." if state.get("spot_pricing_policy_id")
             else "Follows the variable Spot price without an hourly price cap.")
          + " Capacity/recovery are not guaranteed; interrupted Jobs require explicit resubmission.")
    if args.dry_run:
        cli([*command, "--dry-run"])
        print("Configuration validated; no Job was created.")
        return
    if not args.yes:
        raise RuntimeError("Review the command, current price and one-hour bound, then add --yes to launch paid compute.")
    existing = cli(["ai", "job", "get-by-name", "--parent-id", state["project_id"], "--name", state["name"]], allow_not_found=True)
    prior = load_state() if STATE.exists() else {}
    if existing:
        identity = ("name", "files_hash", "project_id", "bucket_id", "run_id", "stop_after_step", "attempt")
        if (any(prior.get(key) != state.get(key) for key in identity)
                or prior.get("id") and prior["id"] != existing.get("metadata", {}).get("id")):
            raise RuntimeError("That Job name already exists but is not this tracked submission. Choose a new run ID.")
        job = existing
        print("Found this tracked attempt; no duplicate Job was created.")
    else:
        if prior.get("name") == state["name"] and prior.get("id") is None:
            raise RuntimeError("A previous submission with this name is unresolved. Inspect the console/operation before choosing a new run ID; this helper will not blindly repeat create.")
        # Persist non-secret intent before sending a write, so an ambiguous response is recoverable by name.
        write_state(STATE, state)
        cli([*command, "--async"], mutation=True)
        job = None
        for _ in range(20):
            job = cli(["ai", "job", "get-by-name", "--parent-id", state["project_id"], "--name", state["name"]], allow_not_found=True)
            if job:
                break
            time.sleep(2)
        if not job:
            raise RuntimeError("Create was submitted but the Job is not visible yet. Inspect by name; do not repeat create blindly.")
    info = job_summary(job)
    if info["project_id"] != state["project_id"] or not info["spot"]:
        raise RuntimeError("Returned Job differs from the selected project/Spot request.")
    state["id"] = info["id"]
    write_state(STATE, state)
    artifact = "recovery-SESSION.zip (checkpoint phase)" if state["stop_after_step"] else "result.zip (when training completes)"
    print(json.dumps({**info, "run_id": state["run_id"], "stop_after_step": state["stop_after_step"],
                      "artifacts": f"Object Storage → {state.get('bucket_name') or state['bucket_id']} → {state['run_id']}/{artifact}"}, indent=2))


def submit(args):
    check_version()
    project, bucket_id, run_id = validate_id(args.project_id, "project"), validate_id(args.bucket_id, "bucket"), validate_run_id(args.run_id)
    validate_stop(args.stop_after_step)
    aggregate, files = file_contract()
    bucket = bucket_details(project, bucket_id)
    if STATE.exists():
        prior = load_state()
        if prior["project_id"] == project and prior["bucket_id"] == bucket_id and prior["run_id"] == run_id:
            if prior["files_hash"] != aggregate:
                raise RuntimeError("Recipe code/config/data changed for this run. Restore the original files or choose a new run ID.")
            if prior["stop_after_step"] != args.stop_after_step:
                raise RuntimeError("Use resume to continue this run with a new Job; do not change its first-phase command.")
            submit_attempt(prior, args)
            return
        current = tracked_job(prior)
        if current.get("status", {}).get("state") not in TERMINAL:
            raise RuntimeError("The currently tracked Job is still active. Finish or cancel it before starting another run.")
    prefix = re.sub(r"[^a-z0-9-]", "-", run_id.lower())[:28].strip("-") or "run"
    identity = json.dumps({"project":project,"bucket":bucket_id,"run":run_id,"files":aggregate},sort_keys=True)
    identity_hash = hashlib.sha256(identity.encode()).hexdigest()[:10]
    name = f"ft-{prefix}-{identity_hash}-phase1"
    state = {"id": None, "name": name, "project_id": project, "bucket_id": bucket_id,
             "bucket_name": bucket.get("metadata", {}).get("name"), "run_id": run_id,
             "stop_after_step": args.stop_after_step, "attempt": 1, "files_hash": aggregate,
             "files": files, "image": IMAGE, "subnet_id": args.subnet_id,
             "spot_pricing_policy_id": args.spot_pricing_policy_id, "previous_jobs": []}
    submit_attempt(state, args)


def resume(args):
    check_version()
    prior = load_state()
    for key in ("project_id", "bucket_id", "run_id"):
        requested = getattr(args, key)
        if requested and requested != prior[key]:
            raise RuntimeError(f"Resume must keep the same {key}; start a different run with submit instead.")
    aggregate, files = file_contract()
    if aggregate != prior["files_hash"]:
        raise RuntimeError("Recipe code/config/data changed. Resume requires the original files and fixed total max_steps.")
    if prior.get("id") is None:
        job = tracked_job(prior)
        print("Recovered the pending submission by name; no new Job was created.")
        print(json.dumps(job_summary(job), indent=2))
        return
    current = tracked_job(prior)
    status = current.get("status", {}).get("state")
    if status not in TERMINAL:
        raise RuntimeError("The current attempt is still active; wait or cancel it before resuming.")
    if status == "COMPLETED" and prior["stop_after_step"] == 0:
        print("The final attempt already completed. Inspect result.zip; no new Job was created.")
        print(json.dumps(job_summary(current), indent=2))
        return
    bucket_details(prior["project_id"], prior["bucket_id"])
    state = dict(prior)
    state["attempt"] += 1
    state["name"] = re.sub(r"-(?:phase1|resume-\d+)$", "", prior["name"]) + f"-resume-{state['attempt']}"
    state["previous_jobs"] = prior.get("previous_jobs", []) + [{"id": prior["id"], "name": prior["name"], "state": status}]
    state["id"], state["stop_after_step"], state["files"] = None, 0, files
    if args.subnet_id:
        state["subnet_id"] = args.subnet_id
    if args.spot_pricing_policy_id:
        state["spot_pricing_policy_id"] = args.spot_pricing_policy_id
    submit_attempt(state, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    bucket = actions.add_parser("create-bucket")
    bucket.add_argument("--project-id", required=True)
    bucket.add_argument("--name", required=True)
    bucket.add_argument("--yes", action="store_true")
    create = actions.add_parser("submit")
    for flag in ("project-id", "bucket-id", "run-id"):
        create.add_argument("--" + flag, required=True)
    create.add_argument("--stop-after-step", type=int, default=50)
    retry = actions.add_parser("resume")
    for flag in ("project-id", "bucket-id", "run-id"):
        retry.add_argument("--" + flag)
    retry.add_argument("--stop-after-step", type=int, choices=[0], default=0)
    for entry in (create, retry):
        entry.add_argument("--subnet-id")
        entry.add_argument("--spot-pricing-policy-id")
        entry.add_argument("--dry-run", action="store_true")
        entry.add_argument("--yes", action="store_true")
    for name in ("status", "logs", "wait", "cancel"):
        action = actions.add_parser(name)
        action.add_argument("--job-id")
        if name == "logs":
            action.add_argument("--tail", type=int, default=100)
            action.add_argument("--since", default="24h")
        if name == "wait":
            action.add_argument("--timeout", type=int, default=3600)
        if name == "cancel":
            action.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "create-bucket":
            create_bucket(args)
        elif args.action == "submit":
            submit(args)
        elif args.action == "resume":
            resume(args)
        else:
            state = load_state()
            job = tracked_job(state, args.job_id)
            if args.action == "status":
                print(json.dumps(job_summary(job), indent=2))
            elif args.action == "logs":
                if not 1 <= args.tail <= 10000:
                    raise RuntimeError("--tail must be between 1 and 10000.")
                print(cli(["ai", "job", "logs", job["metadata"]["id"], "--tail", str(args.tail), "--since", args.since], text=True))
            elif args.action == "wait":
                if args.timeout < 1:
                    raise RuntimeError("--timeout must be positive.")
                deadline, previous = time.monotonic() + args.timeout, None
                while True:
                    info = job_summary(job)
                    if info["state"] != previous:
                        print(json.dumps(info), flush=True)
                        previous = info["state"]
                    if info["state"] in TERMINAL:
                        if info["state"] != "COMPLETED":
                            raise RuntimeError("Job ended without completing. Inspect logs; resume uses saved complete checkpoints.")
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Wait timed out; the Job may still bill. Inspect status or cancel it explicitly.")
                    time.sleep(min(15, max(0, deadline - time.monotonic())))
                    job = tracked_job(state, args.job_id)
            elif args.action == "cancel":
                if job.get("status", {}).get("state") in TERMINAL:
                    print("Job is already terminal; no cancellation needed.")
                    print(json.dumps(job_summary(job), indent=2))
                    return
                command = ["ai", "job", "cancel", "--id", job["metadata"]["id"], "--async"]
                print(shlex.join([CLI, *command]))
                if not args.yes:
                    raise RuntimeError("Add --yes to stop this tracked Job. Complete external checkpoints are retained.")
                cli(command, mutation=True)
                print("Cancellation submitted. Run status to verify the final state; external artifacts were retained.")
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print("Error:", scrub(str(exc)), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
