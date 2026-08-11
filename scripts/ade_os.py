#!/usr/bin/env python3
"""ADE-OS v1 CLI; independent from Ánh Dương Core runtime."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ade_os.core import AdeError, append_memory, bug_records, checkpoint_gate, project_config, read_memory, route_request, search_bugs, write_index


def emit(value: object) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subs = command.add_subparsers(dest="command", required=True)
    project = subs.add_parser("project"); project.add_argument("action", choices=("index", "status")); project.add_argument("--check", action="store_true")
    memory = subs.add_parser("memory"); memory.add_argument("action", choices=("show", "summary", "errors", "tests", "deployments", "checkpoint", "record-error", "record-test", "record-deployment", "set-checkpoint", "clear-checkpoint")); memory.add_argument("--data", default="{}")
    bug = subs.add_parser("bug"); bug.add_argument("action", choices=("list", "search")); bug.add_argument("query", nargs="?")
    route = subs.add_parser("route"); route.add_argument("text"); route.add_argument("--failed-repairs", type=int, default=0); route.add_argument("--dirty-unknown", action="store_true"); route.add_argument("--destructive", action="store_true")
    checkpoint = subs.add_parser("checkpoint"); checkpoint.add_argument("action", choices=("start", "status", "record", "review", "close", "abort")); checkpoint.add_argument("--evidence", type=Path)
    subs.add_parser("validate"); subs.add_parser("doctor")
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = project_config(args.root)
        if args.command == "project":
            if args.action == "index": return emit({"index": str(write_index(args.root, check=args.check))})
            return emit({"project": config, "index": str(args.root / ".ade-os/generated/project-index.json")})
        if args.command == "bug":
            root = args.root / "docs/ade-os/bugs"
            return emit(bug_records(root) if args.action == "list" else search_bugs(root, args.query or ""))
        if args.command == "route": return emit(route_request(args.text, failed_repairs=args.failed_repairs, dirty_unknown=args.dirty_unknown, destructive=args.destructive))
        if args.command == "memory":
            names = {"errors": "last-errors", "tests": "last-passed-tests", "deployments": "deployment-history", "checkpoint": "active-checkpoint"}
            name = names.get(args.action, "runtime-memory")
            if args.action.startswith("record-") or args.action == "set-checkpoint":
                name = {"record-error": "last-errors", "record-test": "last-passed-tests", "record-deployment": "deployment-history", "set-checkpoint": "active-checkpoint"}[args.action]
                return emit(append_memory(args.root, name, json.loads(args.data)))
            return emit(read_memory(args.root, name))
        if args.command == "checkpoint":
            evidence = json.loads(args.evidence.read_text(encoding="utf-8")) if args.evidence else {}
            return emit(checkpoint_gate(evidence, args.action))
        if args.command == "validate":
            write_index(args.root); return emit({"status": "PASS"})
        return emit({"status": "PASS", "artifact_path": config["artifact_path"]})
    except (AdeError, OSError, json.JSONDecodeError) as error:
        print(f"ADE-OS: {error}", file=sys.stderr)
        return 4 if "missing" in str(error) else 1


if __name__ == "__main__":
    raise SystemExit(main())
