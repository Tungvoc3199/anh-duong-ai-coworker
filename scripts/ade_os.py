#!/usr/bin/env python3
"""ADE-OS v1 CLI; independent from Ánh Dương Core runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ade_os.core import (
    AdeError,
    active_checkpoint,
    append_memory,
    bug_records,
    checkpoint_gate,
    evaluate_checkpoint_value_gate,
    project_config,
    read_memory,
    route_request,
    search_bugs,
    validate_checkpoint_start_provenance,
    write_index,
)


def emit(value: object) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def emit_gate(value: dict[str, object]) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value.get("status") == "ALLOW" else 4


def emit_checkpoint(value: dict[str, object]) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value.get("status") == "PASS" else 4


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--root", type=Path)
    subs = command.add_subparsers(dest="command", required=True)
    project = subs.add_parser("project")
    project.add_argument("action", choices=("index", "status"))
    project.add_argument("--check", action="store_true")
    memory = subs.add_parser("memory")
    memory.add_argument(
        "action",
        choices=(
            "show",
            "summary",
            "errors",
            "tests",
            "deployments",
            "checkpoint",
            "record-error",
            "record-test",
            "record-deployment",
            "set-checkpoint",
            "clear-checkpoint",
        ),
    )
    memory.add_argument("--data", default="{}")
    bug = subs.add_parser("bug")
    bug.add_argument("action", choices=("list", "search"))
    bug.add_argument("query", nargs="?")
    route = subs.add_parser("route")
    route.add_argument("text")
    route.add_argument("--failed-repairs", type=int, default=0)
    route.add_argument("--dirty-unknown", action="store_true")
    route.add_argument("--destructive", action="store_true")
    checkpoint = subs.add_parser("checkpoint")
    checkpoint.add_argument(
        "action", choices=("start", "status", "record", "review", "close", "abort")
    )
    checkpoint.add_argument("--evidence", type=Path)
    value_gate = subs.add_parser("value-gate")
    value_gate.add_argument("--manifest", type=Path, required=True)
    subs.add_parser("validate")
    subs.add_parser("doctor")
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.root is None:
        if args.command == "checkpoint" and args.action in {"review", "close"}:
            return emit_checkpoint(
                {
                    "status": "BLOCKED",
                    "reason": "GOVERNANCE_FAILURE",
                    "code": "REPOSITORY_VALIDATION_REQUIRED",
                }
            )
        args.root = Path(__file__).resolve().parents[1]
    try:
        config = project_config(args.root)
        if args.command == "project":
            if args.action == "index":
                return emit({"index": str(write_index(args.root, check=args.check))})
            return emit(
                {
                    "project": config,
                    "index": str(args.root / ".ade-os/generated/project-index.json"),
                }
            )
        if args.command == "bug":
            root = args.root / "docs/ade-os/bugs"
            return emit(
                bug_records(root) if args.action == "list" else search_bugs(root, args.query or "")
            )
        if args.command == "route":
            return emit(
                route_request(
                    args.text,
                    failed_repairs=args.failed_repairs,
                    dirty_unknown=args.dirty_unknown,
                    destructive=args.destructive,
                )
            )
        if args.command == "memory":
            if args.action in {"set-checkpoint", "clear-checkpoint"}:
                return emit_checkpoint(
                    {
                        "status": "BLOCKED",
                        "reason": "GOVERNANCE_FAILURE",
                        "code": "DIRECT_CHECKPOINT_STATE_MUTATION_FORBIDDEN",
                    }
                )
            names = {
                "errors": "last-errors",
                "tests": "last-passed-tests",
                "deployments": "deployment-history",
                "checkpoint": "active-checkpoint",
            }
            name = names.get(args.action, "runtime-memory")
            if args.action.startswith("record-"):
                records = {
                    "record-error": "last-errors",
                    "record-test": "last-passed-tests",
                    "record-deployment": "deployment-history",
                }
                name = records[args.action]
                return emit(append_memory(args.root, name, json.loads(args.data)))
            return emit(read_memory(args.root, name))
        if args.command == "checkpoint":
            evidence = (
                json.loads(args.evidence.read_text(encoding="utf-8")) if args.evidence else {}
            )
            if args.action == "start":
                if args.evidence is None:
                    return emit_checkpoint(
                        {
                            "status": "BLOCKED",
                            "reason": "GOVERNANCE_FAILURE",
                            "code": "CHECKPOINT_PROVENANCE_FAILURE",
                        }
                    )
                artifact_root = Path(
                    str(config.get("artifact_path", "/mnt/f/AIOS/anh-duong-checkpoints"))
                )
                provenance = validate_checkpoint_start_provenance(
                    args.evidence, evidence, artifact_root=artifact_root
                )
                if provenance["status"] != "ALLOW":
                    return emit_checkpoint(
                        {
                            "status": "BLOCKED",
                            "reason": provenance["reason"],
                            "code": provenance.get("code", "CHECKPOINT_PROVENANCE_FAILURE"),
                            "provenance": provenance,
                        }
                    )
            result = checkpoint_gate(evidence, args.action, root=args.root)
            if result["status"] == "PASS" and args.action == "start":
                value_gate = result.get("value_gate")
                value_status = (
                    value_gate.get("status") if isinstance(value_gate, dict) else "NOT_REQUIRED"
                )
                current = active_checkpoint(args.root)
                if current is not None:
                    same = (
                        current.get("checkpoint_id") == evidence.get("checkpoint_id")
                        and current.get("work_type") == evidence.get("work_type")
                        and current.get("value_gate_status") == value_status
                    )
                    if not same:
                        return emit_checkpoint(
                            {
                                "status": "BLOCKED",
                                "reason": "GOVERNANCE_FAILURE",
                                "code": "ACTIVE_CHECKPOINT_CONFLICT",
                                "active_checkpoint_id": current.get("checkpoint_id"),
                            }
                        )
                else:
                    append_memory(
                        args.root,
                        "active-checkpoint",
                        {
                            "checkpoint_id": evidence.get("checkpoint_id"),
                            "work_type": evidence.get("work_type"),
                            "status": "ACTIVE",
                            "value_gate_status": value_status,
                        },
                        limit=20,
                    )
            elif result["status"] == "PASS" and args.action in {"close", "abort"}:
                current = active_checkpoint(args.root)
                if current is None or current.get("checkpoint_id") != evidence.get("checkpoint_id"):
                    return emit_checkpoint(
                        {
                            "status": "BLOCKED",
                            "reason": "GOVERNANCE_FAILURE",
                            "code": "CHECKPOINT_ID_MISMATCH",
                        }
                    )
                append_memory(
                    args.root,
                    "active-checkpoint",
                    {
                        "checkpoint_id": evidence.get("checkpoint_id"),
                        "status": args.action.upper(),
                    },
                    limit=20,
                )
            return emit_checkpoint(result)
        if args.command == "value-gate":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            return emit_gate(evaluate_checkpoint_value_gate(manifest))
        if args.command == "validate":
            write_index(args.root)
            return emit({"status": "PASS"})
        return emit({"status": "PASS", "artifact_path": config["artifact_path"]})
    except (AdeError, OSError, json.JSONDecodeError) as error:
        print(f"ADE-OS: {error}", file=sys.stderr)
        return 4 if "missing" in str(error) else 1


if __name__ == "__main__":
    raise SystemExit(main())
