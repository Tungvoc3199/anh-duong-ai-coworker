#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "ci" / "ruff-baseline.json"


def run_ruff() -> list[dict[str, object]]:
    proc = subprocess.run(
        ["ruff", "check", ".", "--output-format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"ruff failed unexpectedly with exit code {proc.returncode}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"could not parse ruff JSON: {exc}") from exc
    if not isinstance(data, list):
        raise SystemExit("ruff JSON root must be a list")
    return data


def normalize_path(raw: object) -> str:
    path = Path(str(raw))
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def issue_counter(issues: list[dict[str, object]]) -> Counter[tuple[str, str, str]]:
    counter: Counter[tuple[str, str, str]] = Counter()
    for issue in issues:
        path = normalize_path(issue.get("filename", ""))
        code = str(issue.get("code") or "")
        message = str(issue.get("message") or "")
        counter[(path, code, message)] += 1
    return counter


def write_baseline(counter: Counter[tuple[str, str, str]]) -> None:
    entries = [
        {"path": path, "code": code, "message": message, "count": count}
        for (path, code, message), count in sorted(counter.items())
    ]
    payload = {
        "schema": 1,
        "policy": "No new Ruff issue groups or increased counts; reductions are allowed.",
        "tool": "ruff==0.16.0",
        "total": sum(counter.values()),
        "entries": entries,
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"RUFF_BASELINE_WRITTEN={BASELINE_PATH} TOTAL={payload['total']}")


def load_baseline() -> Counter[tuple[str, str, str]]:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != 1:
        raise SystemExit("unsupported Ruff baseline schema")
    counter: Counter[tuple[str, str, str]] = Counter()
    for entry in payload.get("entries", []):
        key = (str(entry["path"]), str(entry["code"]), str(entry["message"]))
        counter[key] = int(entry["count"])
    expected_total = int(payload.get("total", sum(counter.values())))
    if sum(counter.values()) != expected_total:
        raise SystemExit("Ruff baseline total does not match its entries")
    return counter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()

    current = issue_counter(run_ruff())
    if args.write_baseline:
        write_baseline(current)
        return 0

    baseline = load_baseline()
    regressions = current - baseline
    current_total = sum(current.values())
    baseline_total = sum(baseline.values())

    if regressions:
        print(
            f"RUFF_BASELINE=FAIL CURRENT={current_total} BASELINE={baseline_total} "
            f"NEW_OR_INCREASED={sum(regressions.values())}",
            file=sys.stderr,
        )
        for (path, code, message), count in sorted(regressions.items()):
            print(f"+{count} {path} {code}: {message}", file=sys.stderr)
        return 1

    print(f"RUFF_BASELINE=PASS CURRENT={current_total} BASELINE={baseline_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
