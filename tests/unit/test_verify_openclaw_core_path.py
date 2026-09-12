from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from verify_openclaw_core_path import HOST_TOPOLOGY_PROBE, verify_consumer_path  # noqa: E402


def _result(args: list[str], *, stdout: str, rc: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr="")


def test_verifier_uses_configured_container_url_and_authenticated_prepare() -> None:
    calls: list[list[str]] = []

    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] != "docker":
            payload = {
                "core_processes": [
                    {
                        "pid": 100,
                        "port": 8790,
                        "worker_enabled": False,
                        "database_url": "sqlite+pysqlite:////state/anh_duong.db",
                    },
                    {
                        "pid": 200,
                        "port": 8791,
                        "worker_enabled": True,
                        "database_url": "sqlite+pysqlite:////state/anh_duong.db",
                    },
                ]
            }
            return _result(args, stdout=json.dumps(payload) + "\n")
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
    assert result["worker_topology"]["status"] == "PASS"
    assert result["worker_topology"]["same_database_worker_pids"] == [200]
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


def test_verifier_blocks_when_two_worker_enabled_cores_share_target_database() -> None:
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[0] == "docker" and args[1] == "inspect":
            return _result(args, stdout="healthy\n")
        if args[0] == "docker":
            payload = {
                "configured_base_url": "http://host.docker.internal:8792",
                "tested_base_url": "http://host.docker.internal:8792",
                "reachability_http_status": 200,
                "authenticated": True,
                "authenticated_prepare_http_status": 200,
            }
            return _result(args, stdout=json.dumps(payload) + "\n")
        payload = {
            "core_processes": [
                {
                    "pid": 100,
                    "port": 8790,
                    "worker_enabled": True,
                    "database_url": "sqlite+pysqlite:////state/anh_duong.db",
                },
                {
                    "pid": 200,
                    "port": 8792,
                    "worker_enabled": True,
                    "database_url": "sqlite+pysqlite:////state/anh_duong.db",
                },
            ]
        }
        return _result(args, stdout=json.dumps(payload) + "\n")

    result = verify_consumer_path("openclaw-openclaw-gateway-1", run=run)
    assert result["status"] == "BLOCKED"


def test_verifier_normalizes_sqlite_driver_when_detecting_duplicate_workers() -> None:
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[0] == "docker" and args[1] == "inspect":
            return _result(args, stdout="healthy\n")
        if args[0] == "docker":
            payload = {
                "configured_base_url": "http://host.docker.internal:8792",
                "tested_base_url": "http://host.docker.internal:8792",
                "reachability_http_status": 200,
                "authenticated": True,
                "authenticated_prepare_http_status": 200,
            }
            return _result(args, stdout=json.dumps(payload) + "\n")
        payload = {
            "core_processes": [
                {
                    "pid": 100,
                    "port": 8790,
                    "worker_enabled": True,
                    "database_url": "sqlite:////state/anh_duong.db",
                },
                {
                    "pid": 200,
                    "port": 8792,
                    "worker_enabled": True,
                    "database_url": "sqlite+pysqlite:////state/anh_duong.db",
                },
            ]
        }
        return _result(args, stdout=json.dumps(payload) + "\n")

    result = verify_consumer_path("openclaw-openclaw-gateway-1", run=run)
    assert result["status"] == "BLOCKED"


def test_verifier_fails_closed_when_another_core_worker_state_is_unknown() -> None:
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[0] == "docker" and args[1] == "inspect":
            return _result(args, stdout="healthy\n")
        if args[0] == "docker":
            payload = {
                "configured_base_url": "http://host.docker.internal:8792",
                "tested_base_url": "http://host.docker.internal:8792",
                "reachability_http_status": 200,
                "authenticated": True,
                "authenticated_prepare_http_status": 200,
            }
            return _result(args, stdout=json.dumps(payload) + "\n")
        payload = {
            "core_processes": [
                {
                    "pid": 100,
                    "port": 8790,
                    "worker_enabled": None,
                    "database_url": "sqlite+pysqlite:////state/anh_duong.db",
                },
                {
                    "pid": 200,
                    "port": 8792,
                    "worker_enabled": True,
                    "database_url": "sqlite+pysqlite:////state/anh_duong.db",
                },
            ]
        }
        return _result(args, stdout=json.dumps(payload) + "\n")

    result = verify_consumer_path("openclaw-openclaw-gateway-1", run=run)
    assert result["status"] == "BLOCKED"


def test_verifier_ignores_unrelated_uvicorn_app_main_process() -> None:
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[0] == "docker" and args[1] == "inspect":
            return _result(args, stdout="healthy\n")
        if args[0] == "docker":
            payload = {
                "configured_base_url": "http://host.docker.internal:8792",
                "tested_base_url": "http://host.docker.internal:8792",
                "reachability_http_status": 200,
                "authenticated": True,
                "authenticated_prepare_http_status": 200,
            }
            return _result(args, stdout=json.dumps(payload) + "\n")
        payload = {
            "core_processes": [
                {
                    "pid": 172,
                    "port": 8787,
                    "worker_enabled": None,
                    "database_url": None,
                    "is_core": False,
                },
                {
                    "pid": 200,
                    "port": 8792,
                    "worker_enabled": True,
                    "database_url": "sqlite+pysqlite:////state/anh_duong.db",
                    "is_core": True,
                },
            ]
        }
        return _result(args, stdout=json.dumps(payload) + "\n")

    result = verify_consumer_path("openclaw-openclaw-gateway-1", run=run)
    assert result["status"] == "PASS"
    assert result["worker_topology"]["core_process_count"] == 1


def test_verifier_fails_closed_when_effective_core_settings_are_unresolved() -> None:
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[0] == "docker" and args[1] == "inspect":
            return _result(args, stdout="healthy\n")
        if args[0] == "docker":
            payload = {
                "configured_base_url": "http://host.docker.internal:8792",
                "tested_base_url": "http://host.docker.internal:8792",
                "reachability_http_status": 200,
                "authenticated": True,
                "authenticated_prepare_http_status": 200,
            }
            return _result(args, stdout=json.dumps(payload) + "\n")
        payload = {
            "core_processes": [
                {
                    "pid": 200,
                    "port": 8792,
                    "worker_enabled": None,
                    "database_url": None,
                    "is_core": True,
                }
            ]
        }
        return _result(args, stdout=json.dumps(payload) + "\n")

    result = verify_consumer_path("openclaw-openclaw-gateway-1", run=run)
    assert result["status"] == "BLOCKED"
    assert result["worker_topology"]["unknown_worker_state_pids"] == [200]


def test_host_probe_uses_process_executable_when_argv0_is_uvicorn(tmp_path: Path) -> None:
    fake_proc = tmp_path / "proc"
    pid_dir = fake_proc / "321"
    pid_dir.mkdir(parents=True)
    runtime_dir = tmp_path / "anh-duong-core-runtime"
    runtime_dir.mkdir()
    fake_python = tmp_path / "python3.12"
    fake_python.write_text(
        "#!/bin/sh\n"
        'echo \'{"worker_enabled": true, "database_url": '
        '"sqlite+pysqlite:////state/anh_duong.db"}\'\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    (pid_dir / "exe").symlink_to(fake_python)
    (pid_dir / "cwd").symlink_to(runtime_dir, target_is_directory=True)
    (pid_dir / "cmdline").write_bytes(b"uvicorn\0app.main:app\0--port\09876\0")
    (pid_dir / "environ").write_bytes(b"PATH=\0")

    probe = HOST_TOPOLOGY_PROBE.replace('Path("/proc")', f"Path({str(fake_proc)!r})")
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    process = payload["core_processes"][0]
    assert process["port"] == 9876
    assert process["worker_enabled"] is True
    assert process["database_url"] == "sqlite+pysqlite:////state/anh_duong.db"
