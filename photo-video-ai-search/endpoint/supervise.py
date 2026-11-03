"""Fail-together supervisor for one GPU and two model API gateways.

No Endpoint is created here. Any child exit ends the entire container so one
failed service cannot leave an apparently healthy, half-working paid runtime.
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
try:
    from endpoint.gpu_telemetry import GpuTelemetry
except ModuleNotFoundError:
    from gpu_telemetry import GpuTelemetry

HERE = Path(__file__).parent
EMBED_PYTHON = "/usr/bin/python3"
FLUX_PYTHON = "/opt/flux-venv/bin/python"
children = []
stopping = threading.Event()
telemetry = None


def stop(*_):
    stopping.set()
    for child in reversed(children):
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def drain_logs(child, label):
    hidden = [os.environ.get(name, "") for name in ("HF_TOKEN", "EMBEDDING_API_KEY", "GENERATION_API_KEY")]
    for line in iter(child.stdout.readline, ""):
        for value in hidden:
            if value:
                line = line.replace(value, "[redacted]")
        line = re.sub(r"(?i)(bearer\s+)[^\s'\"]+", r"\1[redacted]", line)
        print(f"[{label}] {line.rstrip()[:2000]}", flush=True)


def spawn(command, label, flux=False):
    environment = os.environ.copy()
    if flux:
        # Do not let the embedding image's CUDA 12.9 library path shadow the
        # official generator's CUDA 13.0 wheel libraries in its separate venv.
        site = Path("/opt/flux-venv/lib/python3.12/site-packages")
        libraries = ["/usr/local/nvidia/lib", "/usr/local/nvidia/lib64", str(site / "torch/lib")]
        libraries += [str(path) for path in sorted((site / "nvidia").glob("*/lib"))]
        environment["LD_LIBRARY_PATH"] = ":".join(libraries)
        environment.pop("CUDA_HOME", None)
        environment["PATH"] = "/opt/flux-venv/bin:" + environment.get("PATH", "")
    child = subprocess.Popen(command, env=environment, start_new_session=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    children.append(child)
    threading.Thread(target=drain_logs, args=(child, label), daemon=True).start()
    return child


def wait_ready(child, port, seconds=1200):
    deadline = time.monotonic() + seconds
    while not stopping.is_set() and time.monotonic() < deadline:
        if any(p.poll() is not None for p in children):
            raise RuntimeError("A model process exited during startup.")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        stopping.wait(3)
    raise RuntimeError("Model startup exceeded its bounded wait or was stopped.")


def validate_memory():
    qwen = float(os.environ.get("QWEN_GPU_MEMORY_UTILIZATION", "0.25"))
    pup = float(os.environ.get("PUP_GPU_MEMORY_UTILIZATION", "0.30"))
    # These bounds preserve space for the BF16 image pipeline. They are a
    # starting allocation, not a claim of a measured 96GB deployment.
    if not 0.23 <= qwen <= 0.27 or not 0.28 <= pup <= 0.32 or qwen + pup > 0.57:
        raise RuntimeError("GPU allocations exceed the reviewed demo memory budget.")
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.total,driver_version", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    values = result.stdout.splitlines()
    if len(values) != 1:
        raise RuntimeError("This image requires exactly one visible GPU with at least 90,000 MiB of memory.")
    memory, driver = (part.strip() for part in values[0].split(","))
    if int(memory) < 90000:
        raise RuntimeError("This image requires exactly one visible GPU with at least 90,000 MiB of memory.")
    if tuple(map(int, driver.split("."))) < (580, 65, 6):
        raise RuntimeError("The official FLUX3 CUDA 13.0 stack requires NVIDIA driver 580.65.06 or newer.")
    return qwen


def print_final_gpu_summary(instance, exit_code):
    """Preserve sampled startup/OOM evidence even if public ports never opened."""
    report = instance.snapshot()
    fields = ("source", "scope", "phase", "available", "latest", "latest_sample_age_seconds",
              "stale", "overall", "phase_peaks", "active_operation", "last_operation",
              "error", "error_count", "peak_note", "operation_timing_note")
    summary = {field: report[field] for field in fields}
    summary["exit_code"] = exit_code
    print("[gpu-final] " + json.dumps(summary, allow_nan=False), flush=True)


def main():
    global telemetry
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if not os.environ.get("HF_TOKEN"):
        raise RuntimeError("HF_TOKEN is required; its owner must accept gated model terms first.")
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
    os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")
    telemetry = GpuTelemetry()
    telemetry.reset()
    telemetry.observe()
    telemetry.start(stopping)
    def log_gpu(phase):
        report = telemetry.snapshot()
        print("[gpu] " + json.dumps({"phase": phase, "latest": report["latest"],
                                      "sampled_peaks": report["phase_peaks"].get(phase),
                                      "error": report["error"]}), flush=True)
    log_gpu("startup")
    qwen_memory = validate_memory()
    startup_deadline = time.monotonic() + 1800
    versions = json.loads((HERE / "versions.json").read_text())
    lock_path = Path(os.environ.get("GPU_LOCK_PATH", "/run/cookbook/gpu.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    Path(str(lock_path) + ".unhealthy").unlink(missing_ok=True)

    print("Preparing generation packages; downloads require previously granted model access.", flush=True)
    telemetry.set_phase("weight_download")
    download = spawn([FLUX_PYTHON, str(HERE / "download_weights.py")], "weights", flux=True)
    if download.wait(timeout=max(0.1, startup_deadline - time.monotonic())) != 0:
        raise RuntimeError("Weight preparation failed; check access, network and disk.")
    children.remove(download)
    log_gpu("weight_download")

    print("Starting Qwen embeddings with its capped GPU allocation.", flush=True)
    telemetry.set_phase("embedding_startup")
    embed = spawn([
        EMBED_PYTHON, "-m", "vllm.entrypoints.openai.api_server",
        "--model", versions["embedding_model"], "--revision", versions["embedding_revision"],
        "--served-model-name", versions["embedding_model"], "--runner", "pooling",
        "--trust-remote-code", "--max-model-len", "8192", "--max-num-seqs", "1",
        "--max-num-batched-tokens", "8192", "--gpu-memory-utilization", str(qwen_memory),
        "--limit-mm-per-prompt", '{"image":{"count":1,"width":1024,"height":1024},"video":{"count":1,"num_frames":8,"width":640,"height":480}}',
        "--media-io-kwargs", '{"video":{"num_frames":8}}',
        "--enforce-eager", "--no-enable-log-requests", "--disable-uvicorn-access-log",
        "--host", "127.0.0.1", "--port", "8002",
    ], "embedding")
    wait_ready(embed, 8002, seconds=max(0, min(1200, startup_deadline - time.monotonic())))
    log_gpu("embedding_startup")

    print("Starting FLUX3, its text encoder and the dedicated prompt upsampler.", flush=True)
    telemetry.set_phase("generation_startup")
    generation = spawn([FLUX_PYTHON, str(HERE / "flux_service.py")], "generation", flux=True)
    wait_ready(generation, 8003, seconds=max(0, min(1200, startup_deadline - time.monotonic())))
    log_gpu("generation_startup")
    telemetry.set_phase("idle")

    for kind, port in (("embedding", 8000), ("generation", 8001)):
        gateway = spawn([EMBED_PYTHON, str(HERE / "gateway.py"), kind], f"{kind}-gateway")
        wait_ready(gateway, port, seconds=30)
    print("Ready: embeddings on port 8000; image generation on port 8001. GPU requests are serialized.", flush=True)
    while not stopping.wait(1):
        if any(child.poll() is not None for child in children):
            raise RuntimeError("A model service or gateway exited; stopping all services.")


if __name__ == "__main__":
    code = 0
    try:
        main()
    except Exception as error:
        # Only our deliberately sanitized diagnostic text is public.
        message = str(error) if type(error) is RuntimeError else "Runtime startup or supervision failed."
        print(message, file=sys.stderr, flush=True)
        code = 1
    finally:
        if telemetry is not None:
            try:
                print_final_gpu_summary(telemetry, code)
            except Exception:
                print("[gpu-final] Numeric GPU summary is unavailable.", file=sys.stderr, flush=True)
        stop()
        deadline = time.monotonic() + 15
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        sys.exit(code)
