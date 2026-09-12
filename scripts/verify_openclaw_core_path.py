#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

RunCommand = Callable[[list[str]], subprocess.CompletedProcess[str]]

NODE_PROBE = r"""
const base = (process.env.ANH_DUONG_CORE_BASE_URL || "").replace(/\/+$/, "");
const token = process.env.ANH_DUONG_CORE_INTERNAL_TOKEN || "";
const out = {
  configured_base_url: base,
  tested_base_url: base,
  reachability_http_status: null,
  authenticated: Boolean(token),
  authenticated_prepare_http_status: null,
};
async function requestStatus(url, options = {}) {
  try {
    const response = await fetch(url, {...options, signal: AbortSignal.timeout(5000)});
    return response.status;
  } catch {
    return null;
  }
}
if (base) {
  out.reachability_http_status = await requestStatus(`${base}/health`);
  if (token) {
    out.authenticated_prepare_http_status = await requestStatus(
      `${base}/api/internal/requests/prepare`,
      {
        method: "POST",
        headers: {"Authorization": `Bearer ${token}`, "Content-Type": "application/json"},
        body: JSON.stringify({
          text: "runtime closure consumer-path probe",
          request_id: `runtime_closure_${Date.now()}`,
          actor: "runtime_closure_gate",
        }),
      },
    );
  }
}
console.log(JSON.stringify(out));
const ok = Boolean(base) && out.reachability_http_status === 200 &&
  out.authenticated && out.authenticated_prepare_http_status === 200;
process.exit(ok ? 0 : 1);
""".strip()


HOST_TOPOLOGY_PROBE = r"""
import json
import os
import shutil
import subprocess
from pathlib import Path

processes = []
for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    try:
        exe_path = os.readlink(entry / "exe")
        exe = Path(exe_path).name
        if not exe.startswith("python"):
            continue
        parts = (entry / "cmdline").read_bytes().split(b"\0")
        argv = [part.decode("utf-8", "replace") for part in parts if part]
        if "app.main:app" not in argv or not any("uvicorn" in part for part in argv):
            continue
        port = None
        if "--port" in argv:
            index = argv.index("--port")
            if index + 1 < len(argv):
                port = int(argv[index + 1])
        env = {}
        for item in (entry / "environ").read_bytes().split(b"\0"):
            if b"=" not in item:
                continue
            key, value = item.split(b"=", 1)
            env[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
        cwd = os.readlink(entry / "cwd")
        is_core = any(key.startswith("ANH_DUONG_") for key in env) or (
            "anh-duong-core" in cwd
        )
        if not is_core:
            continue
        python_cmd = argv[0]
        if not Path(python_cmd).name.startswith("python"):
            resolved_entry = shutil.which(python_cmd, path=env.get("PATH"))
            sibling_python = (
                Path(resolved_entry).with_name("python") if resolved_entry else None
            )
            if sibling_python is not None and sibling_python.exists():
                python_cmd = str(sibling_python)
            else:
                python_cmd = exe_path
        probe_env = dict(env)
        probe_env["PYTHONDONTWRITEBYTECODE"] = "1"
        settings_code = (
            'import json; from app.config import Settings; s=Settings(); '
            'print(json.dumps({"worker_enabled": s.async_worker_enabled, '
            '"database_url": s.database_url}))'
        )
        resolved_worker = None
        resolved_database = None
        try:
            settings_probe = subprocess.run(
                [python_cmd, "-c", settings_code],
                cwd=cwd,
                env=probe_env,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if settings_probe.returncode == 0:
                for line in reversed(settings_probe.stdout.splitlines()):
                    try:
                        effective = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(effective, dict):
                        worker_value = effective.get("worker_enabled")
                        database_value = effective.get("database_url")
                        if isinstance(worker_value, bool):
                            resolved_worker = worker_value
                        if isinstance(database_value, str) and database_value.strip():
                            resolved_database = database_value
                        break
        except (OSError, subprocess.SubprocessError):
            pass
        processes.append({
            "pid": int(entry.name),
            "port": port,
            "worker_enabled": resolved_worker,
            "database_url": resolved_database,
            "is_core": True,
        })
    except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
        continue
print(json.dumps({"core_processes": processes}, sort_keys=True))
""".strip()


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=15)


def _last_json_line(stdout: str) -> dict[str, object] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _database_identity(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value)
    base_scheme = parsed.scheme.split("+", 1)[0].lower()
    if base_scheme == "sqlite":
        return f"sqlite:{parsed.path}"
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        return None
    host = parsed.hostname or ""
    return f"{base_scheme}://{host}{port}{parsed.path}"


def _database_fingerprint(value: object) -> str | None:
    identity = _database_identity(value)
    if not identity:
        return None
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _verify_worker_topology(
    configured_base_url: object,
    *,
    run: RunCommand,
) -> dict[str, object]:
    if not isinstance(configured_base_url, str) or not configured_base_url.strip():
        return {"status": "BLOCKED", "reason": "missing_configured_base_url"}
    try:
        target_port = urlparse(configured_base_url).port
    except ValueError:
        target_port = None
    if target_port is None:
        return {"status": "BLOCKED", "reason": "missing_target_port"}

    probe = run([sys.executable, "-c", HOST_TOPOLOGY_PROBE])
    payload = _last_json_line(probe.stdout) or {}
    raw_processes = payload.get("core_processes")
    if probe.returncode != 0 or not isinstance(raw_processes, list):
        return {"status": "BLOCKED", "reason": "topology_probe_failed", "target_port": target_port}

    processes = [
        dict(item)
        for item in raw_processes
        if isinstance(item, dict) and item.get("is_core", True) is not False
    ]

    target = [item for item in processes if item.get("port") == target_port]
    enabled = [item for item in processes if item.get("worker_enabled") is True]
    unknown_worker_state = [
        item for item in processes if item.get("worker_enabled") not in (True, False)
    ]
    unknown_db_enabled = [
        item for item in enabled if _database_identity(item.get("database_url")) is None
    ]

    target_db = target[0].get("database_url") if len(target) == 1 else None
    target_db_identity = _database_identity(target_db)
    same_db_enabled = [
        item
        for item in enabled
        if target_db_identity and _database_identity(item.get("database_url")) == target_db_identity
    ]
    passed = (
        len(target) == 1
        and target[0].get("worker_enabled") is True
        and bool(target_db_identity)
        and not unknown_worker_state
        and not unknown_db_enabled
        and len(same_db_enabled) == 1
        and same_db_enabled[0].get("pid") == target[0].get("pid")
    )
    return {
        "status": "PASS" if passed else "BLOCKED",
        "reason": None if passed else "worker_topology_not_singleton",
        "target_port": target_port,
        "target_pid": target[0].get("pid") if len(target) == 1 else None,
        "database_fingerprint": _database_fingerprint(target_db),
        "worker_enabled_pids": [item.get("pid") for item in enabled],
        "unknown_worker_state_pids": [item.get("pid") for item in unknown_worker_state],
        "same_database_worker_pids": [item.get("pid") for item in same_db_enabled],
        "core_process_count": len(processes),
    }


def verify_consumer_path(container: str, *, run: RunCommand = _run) -> dict[str, object]:
    health = run(
        [
            "docker",
            "inspect",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
            container,
        ]
    )
    openclaw_healthy = health.returncode == 0 and health.stdout.strip() == "healthy"

    probe = run(["docker", "exec", container, "node", "--input-type=module", "-e", NODE_PROBE])
    payload = _last_json_line(probe.stdout) or {}
    consumer_path: dict[str, object] = {
        "openclaw_healthy": openclaw_healthy,
        "configured_base_url": payload.get("configured_base_url"),
        "tested_base_url": payload.get("tested_base_url"),
        "reachability_http_status": payload.get("reachability_http_status"),
        "authenticated": payload.get("authenticated") is True,
        "authenticated_prepare_http_status": payload.get("authenticated_prepare_http_status"),
    }
    configured = consumer_path["configured_base_url"]
    tested = consumer_path["tested_base_url"]
    worker_topology = _verify_worker_topology(configured, run=run)
    passed = (
        openclaw_healthy
        and isinstance(configured, str)
        and bool(configured.strip())
        and configured == tested
        and consumer_path["reachability_http_status"] == 200
        and consumer_path["authenticated"] is True
        and consumer_path["authenticated_prepare_http_status"] == 200
        and probe.returncode == 0
        and worker_topology["status"] == "PASS"
    )
    return {
        "status": "PASS" if passed else "BLOCKED",
        "consumer_path": consumer_path,
        "worker_topology": worker_topology,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify OpenClaw -> configured Core consumer path."
    )
    parser.add_argument("--container", default="openclaw-openclaw-gateway-1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_consumer_path(args.container)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
