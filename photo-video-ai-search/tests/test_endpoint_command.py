"""The deployment helper must never provision or silently change pricing mode."""
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest


HELPER = Path(__file__).parents[1] / "scripts" / "endpoint-command.sh"


@pytest.fixture
def deployment(tmp_path):
    log = tmp_path / "cli-calls.json"
    stub = tmp_path / "nebius"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['CLI_CALL_LOG']).write_text(json.dumps(\n"
        "    {'args': sys.argv[1:], 'agent': os.environ.get('AI_AGENT')}))\n"
    )
    stub.chmod(0o755)
    environment = os.environ.copy()
    for name in ("PRICING_MODEL", "SPOT_PRICING_POLICY_ID", "SPOT_FOLLOWS_PRICE",
                 "REGISTRY_SECRET", "ENDPOINT_NAME"):
        environment.pop(name, None)
    environment.update(
        PROJECT_ID="project-fixture123", SUBNET_ID="vpcsubnet-fixture123",
        ENDPOINT_IMAGE="registry.example.invalid/cookbook:test",
        GPU_PLATFORM="gpu-h200-sxm", GPU_PRESET="1gpu-16vcpu-200gb",
        HF_TOKEN_SECRET="fixture-hf-secret", AI_AGENT="fixture-agent",
        PATH=str(tmp_path) + os.pathsep + environment["PATH"], CLI_CALL_LOG=str(log),
    )

    def invoke(*arguments, **settings):
        result = subprocess.run(["bash", str(HELPER), *arguments],
                                env={**environment, **settings}, capture_output=True,
                                text=True, timeout=10, check=False)
        calls = json.loads(log.read_text()) if log.exists() else None
        return result, calls

    return invoke


@pytest.mark.parametrize("settings, expected", [
    ({}, ["--on-demand"]),
    ({"PRICING_MODEL": "regular"}, ["--on-demand"]),
    ({"PRICING_MODEL": "spot", "SPOT_PRICING_POLICY_ID": "pricingpolicy-fixture123"},
     ["--preemptible", "--spot-pricing-policy-id", "pricingpolicy-fixture123"]),
    ({"PRICING_MODEL": "spot", "SPOT_FOLLOWS_PRICE": "yes"},
     ["--preemptible", "--follows-spot-price"]),
])
def test_prints_explicit_pricing_without_running_cli(deployment, settings, expected):
    result, calls = deployment(**settings)
    assert result.returncode == 0, result.stderr
    assert calls is None
    command = shlex.split(result.stdout)
    for item in expected:
        assert item in command
    assert ("--on-demand" in command) != ("--preemptible" in command)
    assert command[command.index("--name") + 1].endswith("-spot") == (
        settings.get("PRICING_MODEL") == "spot")
    assert command.count("--container-port") == 2
    assert command[command.index("--auth") + 1] == "token"
    assert "--token" not in command
    assert "HF_TOKEN=fixture-hf-secret" in command


@pytest.mark.parametrize("settings", [
    {"PRICING_MODEL": "spot"},
    {"PRICING_MODEL": "spot", "SPOT_FOLLOWS_PRICE": "maybe"},
    {"PRICING_MODEL": "spot", "SPOT_PRICING_POLICY_ID": "pricingpolicy-fixture123",
     "SPOT_FOLLOWS_PRICE": "yes"},
    {"PRICING_MODEL": "spot", "SPOT_PRICING_POLICY_ID": "other-resource123"},
    {"PRICING_MODEL": "spot", "SPOT_PRICING_POLICY_ID": "pricingpolicy-REPLACE"},
    {"PRICING_MODEL": "regular", "SPOT_PRICING_POLICY_ID": "pricingpolicy-fixture123"},
    {"PRICING_MODEL": "regular", "SPOT_FOLLOWS_PRICE": "yes"},
    {"PRICING_MODEL": "automatic"},
    {"GPU_PLATFORM": "gpu-h100-sxm"},
    {"GPU_PLATFORM": "gpu-h200-sxm", "GPU_PRESET": "1gpu-24vcpu-218gb"},
])
def test_rejects_ambiguous_pricing_or_unsupported_hardware(deployment, settings):
    result, calls = deployment("--dry-run", **settings)
    assert result.returncode == 2
    assert calls is None
    assert not result.stdout


@pytest.mark.parametrize("platform", ["gpu-rtx6000", "gpu-rtx6000-a"])
def test_retains_reviewed_rtx_pair(deployment, platform):
    result, calls = deployment(GPU_PLATFORM=platform, GPU_PRESET="1gpu-24vcpu-218gb")
    assert result.returncode == 0, result.stderr
    assert calls is None


def test_dry_run_executes_only_validation_and_preserves_agent(deployment):
    result, calls = deployment("--dry-run", PRICING_MODEL="spot",
                               SPOT_PRICING_POLICY_ID="pricingpolicy-fixture123")
    assert result.returncode == 0, result.stderr
    assert calls["agent"] == "fixture-agent"
    assert calls["args"][:3] == ["ai", "endpoint", "create"]
    assert "--dry-run" in calls["args"]
    assert "--preemptible" in calls["args"]
    assert "--on-demand" not in calls["args"]
    assert "--follows-spot-price" not in calls["args"]
