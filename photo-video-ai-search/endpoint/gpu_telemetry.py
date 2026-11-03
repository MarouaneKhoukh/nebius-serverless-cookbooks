"""Numeric, whole-GPU nvidia-smi samples shared across the runtime processes.

All writers use a separate advisory lock and atomic replace. No process list,
command line, GPU UUID, model prompt or environment variable enters the report.
Peaks are maxima of observations, not CUDA allocator high-water marks.
"""
import copy
import fcntl
import json
import math
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PHASES = {"startup", "weight_download", "embedding_startup", "generation_startup",
          "idle", "embedding", "generation", "shutdown"}
STARTUP_SUBPHASES = {"weight_download", "embedding_startup", "generation_startup"}
ROLES = {"embedding", "generation"}
PEAK_NOTE = "Sampled whole-GPU maxima, not allocator high-water marks; brief spikes may be missed."


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def empty_peaks():
    return {"sample_count": 0, "sampled_peak_memory_used_mib": None,
            "sampled_peak_utilization_gpu_percent": None}


def update_peaks(target, sample):
    target["sample_count"] += 1
    for source, destination in (("memory_used_mib", "sampled_peak_memory_used_mib"),
                                ("utilization_gpu_percent", "sampled_peak_utilization_gpu_percent")):
        value = sample[source]
        if value is not None:
            previous = target[destination]
            target[destination] = value if previous is None else max(previous, value)


def parse_sample(stdout):
    """Parse only the three explicitly requested numeric columns for one GPU."""
    rows = [line.strip() for line in stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError("Expected one GPU row.")
    fields = [part.strip() for part in rows[0].split(",")]
    if len(fields) != 3:
        raise ValueError("Unexpected sample columns.")
    used, total = (float(value) for value in fields[:2])
    if not all(math.isfinite(value) for value in (used, total)) or not 0 <= used <= total or total <= 0:
        raise ValueError("Invalid memory values.")
    warnings = []
    if fields[2] in {"N/A", "[N/A]", "[Not Supported]", "Not Supported"}:
        utilization = None
        warnings.append("GPU utilization is unavailable from nvidia-smi.")
    else:
        utilization = float(fields[2])
        if not math.isfinite(utilization) or not 0 <= utilization <= 100:
            raise ValueError("Invalid utilization value.")
    return {"memory_used_mib": used, "memory_total_mib": total,
            "memory_free_mib": total - used, "utilization_gpu_percent": utilization,
            "warnings": warnings}


class GpuTelemetry:
    def __init__(self, path=None, runner=None, interval_seconds=1.0):
        default = Path(os.environ.get("GPU_LOCK_PATH", "/run/cookbook/gpu.lock")).with_name("gpu-telemetry.json")
        self.path = Path(path or os.environ.get("GPU_TELEMETRY_PATH", str(default)))
        self.runner = runner or subprocess.run
        self.interval = float(interval_seconds)
        if not 0.5 <= self.interval <= 10:
            raise ValueError("Telemetry interval must be between 0.5 and 10 seconds.")

    def initial_state(self):
        return {"version": 1, "source": "nvidia-smi", "scope": "whole visible GPU",
                "target_sampling_interval_seconds": self.interval, "peak_note": PEAK_NOTE,
                "operation_timing_note": "Operation duration covers the GPU-lock window, including boundary samples; it is not pure model latency.",
                "started_at": utc_now(), "available": False, "error": "No successful sample yet.",
                "error_count": 0, "phase": "startup", "latest": None,
                "overall": empty_peaks(), "phase_peaks": {}, "active_operation": None,
                "last_operation": None, "operation_sequence": 0,
                "operations_by_role": {role: {"completed": 0, "last": None} for role in sorted(ROLES)}}

    @contextmanager
    def locked_state(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.path) + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                try:
                    state = json.loads(self.path.read_text())
                    if state.get("version") != 1:
                        raise ValueError
                except (OSError, ValueError, AttributeError):
                    state = self.initial_state()
                yield state
                temporary = self.path.with_name(self.path.name + ".tmp")
                temporary.write_text(json.dumps(state, allow_nan=False, separators=(",", ":")))
                os.replace(temporary, self.path)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def reset(self):
        with self.locked_state() as state:
            state.clear()
            state.update(self.initial_state())

    def set_phase(self, phase):
        if phase not in PHASES:
            raise ValueError("Unsupported telemetry phase.")
        with self.locked_state() as state:
            state["phase"] = phase

    def _error(self, message):
        with self.locked_state() as state:
            state["available"] = False
            state["error"] = message
            state["error_count"] += 1

    def observe(self):
        with self.locked_state() as state:
            phase = state["phase"]
            operation = state["active_operation"]
            sequence = operation["sequence"] if operation else None
        try:
            result = self.runner(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, check=True, timeout=2,
            )
            sample = parse_sample(result.stdout)
        except FileNotFoundError:
            self._error("nvidia-smi is unavailable.")
            return None
        except subprocess.TimeoutExpired:
            self._error("nvidia-smi sampling timed out.")
            return None
        except (subprocess.SubprocessError, OSError, ValueError, TypeError):
            # stderr and exceptions can contain host details; never expose them.
            self._error("nvidia-smi did not return a valid numeric sample.")
            return None
        sample["sampled_at"] = utc_now()
        sample["_sampled_epoch"] = time.time()
        with self.locked_state() as state:
            state["available"] = True
            state["error"] = None
            state["latest"] = sample
            update_peaks(state["overall"], sample)
            active = state["active_operation"]
            same_operation = (active["sequence"] if active else None) == sequence
            # A sample spanning a phase boundary cannot be assigned reliably.
            if state["phase"] == phase and same_operation:
                update_peaks(state["phase_peaks"].setdefault(phase, empty_peaks()), sample)
                if phase in STARTUP_SUBPHASES:
                    update_peaks(state["phase_peaks"].setdefault("startup", empty_peaks()), sample)
                if active:
                    update_peaks(active, sample)
        return sample

    def begin_operation(self, role):
        if role not in ROLES:
            raise ValueError("Unsupported GPU operation role.")
        with self.locked_state() as state:
            state["operation_sequence"] += 1
            state["phase"] = role
            state["active_operation"] = {"sequence": state["operation_sequence"], "role": role,
                                         "started_at": utc_now(), "_started_monotonic": time.monotonic(),
                                         **empty_peaks()}
            return state["operation_sequence"]

    def end_operation(self, sequence):
        with self.locked_state() as state:
            operation = state["active_operation"]
            if operation is None or operation["sequence"] != sequence:
                return
            operation["ended_at"] = utc_now()
            operation["duration_seconds"] = round(time.monotonic() - operation.pop("_started_monotonic"), 4)
            state["last_operation"] = copy.deepcopy(operation)
            by_role = state["operations_by_role"][operation["role"]]
            by_role["completed"] += 1
            by_role["last"] = copy.deepcopy(operation)
            state["active_operation"] = None
            state["phase"] = "idle"

    @contextmanager
    def operation(self, role):
        """Boundary samples supplement the supervisor's periodic observations."""
        sequence = self.begin_operation(role)
        self.observe()
        try:
            yield
        finally:
            self.observe()
            self.end_operation(sequence)

    def start(self, stop_event):
        def poll():
            while not stop_event.is_set():
                self.observe()
                stop_event.wait(self.interval)
        thread = threading.Thread(target=poll, name="numeric-gpu-telemetry", daemon=True)
        thread.start()
        return thread

    def snapshot(self):
        try:
            with self.locked_state() as state:
                report = copy.deepcopy(state)
        except OSError:
            report = self.initial_state()
            report["error"] = "GPU telemetry storage is unavailable."
        latest = report["latest"]
        report["latest_sample_age_seconds"] = round(max(0, time.time() - latest["_sampled_epoch"]), 3) if latest else None
        report["stale"] = latest is None or report["latest_sample_age_seconds"] > self.interval * 3 + 2
        def public(value):
            if isinstance(value, dict):
                return {key: public(item) for key, item in value.items() if not key.startswith("_")}
            if isinstance(value, list):
                return [public(item) for item in value]
            return value
        return public(report)
