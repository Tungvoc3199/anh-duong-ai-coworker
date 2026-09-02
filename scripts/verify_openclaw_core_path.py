#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

RunCommand = Callable[[list[str]], subprocess.CompletedProcess[str]]

NODE_PROBE = r'''
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
'''.strip()


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


def verify_consumer_path(container: str, *, run: RunCommand = _run) -> dict[str, object]:
    health = run([
        "docker", "inspect", "--format",
        "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
        container,
    ])
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
    passed = (
        openclaw_healthy
        and isinstance(configured, str) and bool(configured.strip())
        and configured == tested
        and consumer_path["reachability_http_status"] == 200
        and consumer_path["authenticated"] is True
        and consumer_path["authenticated_prepare_http_status"] == 200
        and probe.returncode == 0
    )
    return {"status": "PASS" if passed else "BLOCKED", "consumer_path": consumer_path}


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
