#!/usr/bin/env python3
"""Operator cutover for the prepared Core release; no gateway or permission changes."""

import argparse
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path("/home/thadc/AIOS/releases/anh-duong-core")
RELEASE = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "current"
CHECKPOINT = Path("/mnt/f/AIOS/anh-duong-checkpoints/AD-RUNTIME-TASK-RELIABILITY-1")


def ready():
    for _ in range(20):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8790/ready", timeout=2) as response:
                if json.load(response).get("status") == "ready":
                    return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("Core readiness failed")


def point(target):
    staging = ROOT / "current.runtime-reliability-stage"
    if staging.exists() or staging.is_symlink():
        raise RuntimeError("Unexpected staged pointer; inspect before continuing")
    staging.symlink_to(target, target_is_directory=True)
    os.replace(staging, CURRENT)


def verify():
    subprocess.run(
        [
            "python3",
            str(RELEASE / "scripts/verify_openclaw_core_path.py"),
            "--output",
            str(CHECKPOINT / "operator-consumer-path.json"),
        ],
        check=True,
    )


def restart():
    subprocess.run(
        ["systemctl", "--no-ask-password", "restart", "anh-duong-core.service"],
        check=True,
        timeout=45,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if RELEASE.parent != ROOT or RELEASE.name in {"current", "a55fcc3"}:
        raise SystemExit("Run the script from the prepared immutable release.")
    if CURRENT.resolve().name != "a55fcc3":
        raise SystemExit("Active release changed; re-review required.")
    if not (RELEASE / ".venv/bin/python").exists():
        raise SystemExit("Prepared release virtualenv is unavailable.")
    ready()
    verify()
    if args.check:
        print("PRECHECK PASS. No changes applied.")
        return
    if os.geteuid() != 0:
        raise SystemExit("Operator admin session required for system-service restart.")
    old = os.readlink(CURRENT)
    status = {"previous": old, "candidate": str(RELEASE), "status": "applying"}
    (CHECKPOINT / "operator-cutover.json").write_text(json.dumps(status, indent=2))
    switched = False
    try:
        point(RELEASE)
        switched = True
        restart()
        ready()
        verify()
    except Exception:
        if switched:
            point(old)
            restart()
            ready()
            verify()
        status["status"] = "rolled_back"
        (CHECKPOINT / "operator-cutover.json").write_text(json.dumps(status, indent=2))
        raise
    status["status"] = "deployed_telegram_e2e_pending"
    (CHECKPOINT / "operator-cutover.json").write_text(json.dumps(status, indent=2))
    print("DEPLOYED. Fresh Telegram E2E is still required before CLOSED.")


if __name__ == "__main__":
    main()
