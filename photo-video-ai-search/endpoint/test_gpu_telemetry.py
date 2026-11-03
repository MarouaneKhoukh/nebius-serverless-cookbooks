"""Numeric fixtures only: no GPU, weights, credentials or cloud access."""
import subprocess
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

try:
    from endpoint.gpu_telemetry import GpuTelemetry, parse_sample
    from endpoint.gateway import create_app
    from endpoint.supervise import print_final_gpu_summary
except ModuleNotFoundError:
    from gpu_telemetry import GpuTelemetry, parse_sample
    from gateway import create_app
    from supervise import print_final_gpu_summary


class GpuTelemetryTests(unittest.TestCase):
    def sampler(self, path, rows):
        samples = iter(rows)
        return GpuTelemetry(path=path, runner=lambda *args, **kwargs: SimpleNamespace(stdout=next(samples)))

    def test_numeric_columns_and_unavailable_utilization(self):
        sample = parse_sample("24576, 96256, 84\n")
        self.assertEqual(sample["memory_used_mib"], 24576)
        self.assertEqual(sample["memory_free_mib"], 71680)
        self.assertEqual(sample["utilization_gpu_percent"], 84)
        self.assertIsNone(parse_sample("24576, 96256, [N/A]")["utilization_gpu_percent"])
        for row in ("nan, 96256, 8", "999999, 96256, 8", "1,2,101", "1,2,3\n4,5,6", "GPU-uuid,2,3"):
            with self.subTest(row=row), self.assertRaises(ValueError):
                parse_sample(row)

    def test_startup_idle_and_operation_peaks_remain_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            telemetry = self.sampler(Path(folder) / "metrics.json", [
                "1000,96256,2", "30000,96256,65", "24000,96256,0",
                "24500,96256,10", "55000,96256,95", "42000,96256,15",
                "42500,96256,4", "44000,96256,75",
            ])
            telemetry.reset()
            telemetry.observe()
            telemetry.set_phase("embedding_startup")
            telemetry.observe()
            telemetry.set_phase("idle")
            telemetry.observe()
            with telemetry.operation("generation"):
                telemetry.observe()
            with telemetry.operation("embedding"):
                pass
            report = telemetry.snapshot()
        self.assertEqual(report["overall"]["sampled_peak_memory_used_mib"], 55000)
        self.assertEqual(report["phase_peaks"]["embedding_startup"]["sampled_peak_memory_used_mib"], 30000)
        self.assertEqual(report["phase_peaks"]["startup"]["sampled_peak_memory_used_mib"], 30000)
        self.assertEqual(report["phase_peaks"]["idle"]["sampled_peak_memory_used_mib"], 24000)
        generation = report["operations_by_role"]["generation"]["last"]
        self.assertEqual(generation["sampled_peak_memory_used_mib"], 55000)
        self.assertEqual(generation["sample_count"], 3)
        self.assertEqual(generation["role"], "generation")
        self.assertIn("started_at", generation)
        self.assertIn("ended_at", generation)
        self.assertGreaterEqual(generation["duration_seconds"], 0)
        self.assertEqual(report["last_operation"]["role"], "embedding")
        self.assertEqual(report["last_operation"]["sample_count"], 2)
        self.assertIsNone(report["active_operation"])
        self.assertEqual(report["phase"], "idle")

    def test_failed_sampling_is_sanitized_and_keeps_previous_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            telemetry = self.sampler(Path(folder) / "metrics.json", ["12000,96256,5"])
            telemetry.observe()
            telemetry.runner = lambda *args, **kwargs: (_ for _ in ()).throw(
                subprocess.CalledProcessError(1, "private-command", stderr="private-host-detail"))
            self.assertIsNone(telemetry.observe())
            report = telemetry.snapshot()
        self.assertFalse(report["available"])
        self.assertEqual(report["latest"]["memory_used_mib"], 12000)
        self.assertEqual(report["error_count"], 1)
        self.assertNotIn("private", str(report))

    def test_short_operation_still_gets_start_and_end_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            telemetry = self.sampler(Path(folder) / "metrics.json", ["20000,96256,0", "22000,96256,75"])
            with telemetry.operation("embedding"):
                pass
            operation = telemetry.snapshot()["last_operation"]
        self.assertEqual(operation["sample_count"], 2)
        self.assertEqual(operation["sampled_peak_memory_used_mib"], 22000)

    def test_gateway_exposes_existing_metrics_on_both_ports_without_sampling(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "metrics.json"
            telemetry = self.sampler(path, ["44000,96256,10"])
            telemetry.observe()
            with patch.dict("os.environ", {"GPU_TELEMETRY_PATH": str(path)}):
                for kind in ("embedding", "generation"):
                    report = TestClient(create_app(kind)).get("/v1/runtime/gpu").json()
                    self.assertEqual(report["source"], "nvidia-smi")
                    self.assertEqual(report["latest"]["memory_used_mib"], 44000)
                    self.assertIn("brief spikes may be missed", report["peak_note"])
                    self.assertFalse(report["stale"])
                    self.assertNotIn("_sampled_epoch", str(report))
                    self.assertNotIn("UUID", str(report))

    def test_cross_process_style_instances_share_operation_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "metrics.json"
            supervisor = self.sampler(path, ["50000,96256,90"])
            gateway = self.sampler(path, ["30000,96256,0", "35000,96256,5"])
            with gateway.operation("generation"):
                supervisor.observe()
            self.assertEqual(supervisor.snapshot()["last_operation"]["sampled_peak_memory_used_mib"], 50000)

    def test_sample_spanning_phase_transition_is_not_misattributed(self):
        with tempfile.TemporaryDirectory() as folder:
            telemetry = GpuTelemetry(path=Path(folder) / "metrics.json")
            def changed_during_sample(*args, **kwargs):
                telemetry.set_phase("idle")
                return SimpleNamespace(stdout="20000,96256,60")
            telemetry.runner = changed_during_sample
            telemetry.set_phase("embedding_startup")
            telemetry.observe()
            report = telemetry.snapshot()
        self.assertEqual(report["overall"]["sample_count"], 1)
        self.assertEqual(report["phase_peaks"], {})

    def test_final_log_preserves_failed_startup_peak_without_public_gateway(self):
        with tempfile.TemporaryDirectory() as folder:
            telemetry = self.sampler(Path(folder) / "metrics.json", ["93000,96256,99"])
            telemetry.set_phase("generation_startup")
            telemetry.observe()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                print_final_gpu_summary(telemetry, exit_code=1)
            line = output.getvalue().strip()
        self.assertTrue(line.startswith("[gpu-final] "))
        report = json.loads(line.removeprefix("[gpu-final] "))
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["phase"], "generation_startup")
        self.assertEqual(report["phase_peaks"]["generation_startup"]["sampled_peak_memory_used_mib"], 93000)
        self.assertEqual(report["phase_peaks"]["startup"]["sampled_peak_memory_used_mib"], 93000)
        self.assertNotIn("_sampled_epoch", line)


if __name__ == "__main__":
    unittest.main()
