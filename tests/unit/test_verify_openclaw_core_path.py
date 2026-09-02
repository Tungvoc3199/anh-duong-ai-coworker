from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from verify_openclaw_core_path import verify_consumer_path  # noqa: E402


def _result(args: list[str], *, stdout: str, rc: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr="")


def test_verifier_uses_configured_container_url_and_authenticated_prepare() -> None:
    calls: list[list[str]] = []

    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[1] == "inspect":
            return _result(args, stdout="healthy\n")
        payload = {
            "configured_base_url": "http://host.docker.internal:8791",
            "tested_base_url": "http://host.docker.internal:8791",
            "reachability_http_status": 200,
            "authenticated": True,
            "authenticated_prepare_http_status": 200,
        }
        return _result(args, stdout=json.dumps(payload) + "\n")

    result = verify_consumer_path("openclaw-openclaw-gateway-1", run=run)
    assert result["status"] == "PASS"
    assert result["consumer_path"]["configured_base_url"].endswith(":8791")
    command_text = "\n".join(" ".join(call) for call in calls)
    assert "host.docker.internal:8790" not in command_text
    assert "ANH_DUONG_CORE_BASE_URL" in command_text
    assert "ANH_DUONG_CORE_INTERNAL_TOKEN" in command_text


def test_verifier_fails_closed_when_prepare_is_not_authenticated() -> None:
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[1] == "inspect":
            return _result(args, stdout="healthy\n")
        payload = {
            "configured_base_url": "http://host.docker.internal:8791",
            "tested_base_url": "http://host.docker.internal:8791",
            "reachability_http_status": 200,
            "authenticated": False,
            "authenticated_prepare_http_status": 401,
        }
        return _result(args, stdout=json.dumps(payload) + "\n", rc=1)

    result = verify_consumer_path("openclaw-openclaw-gateway-1", run=run)
    assert result["status"] == "BLOCKED"
    assert result["consumer_path"]["authenticated_prepare_http_status"] == 401
