---
description: "Use when: diagnosing, fixing, reviewing, or closing an AIOS checkpoint."
applyTo: "**"
---
# Checkpoint workflow

Before any mutation, inspect the current checkpoint artifacts, `git status --short`, active modifications, and runtime health. Preserve unrelated work exactly.

Use this escalation: **Diagnose → Fix → Deep Debug when a first repair fails or the cause remains unclear → Review**. Work one complete objective at a time.

For every checkpoint, `checkpoint start` requires `checkpoint_id` and `work_type`. For `feature`, `automation`, `integration`, or `custom_build`, the start evidence must also contain a passing `value_gate` with `user_value`, `measurement`, `revenue_link`, `content_proof`, and native decision `USE_NATIVE | WRAP_NATIVE | EXTEND_NATIVE | BUILD_CUSTOM`. `BUILD_CUSTOM` is blocked when native coverage is at least 80% and the missing behavior is not an Ánh Dương-owned control-plane contract. The standalone `python3 scripts/ade_os.py value-gate --manifest <value-gate.json>` command is only a preflight preview; mutation enforcement uses `python3 scripts/ade_os.py checkpoint start --evidence <start.json>` plus the PreToolUse active-checkpoint gate.

For a repair: capture evidence, back up every existing target, make the smallest scoped change, run targeted tests, then relevant regression and runtime/E2E verification. Record artifact paths, exact commands/results, diff scope, and rollback.

A closure requires proven gates, no secret disclosure, and review evidence. Do not invent a formal checkpoint ID; use the active roadmap/checkpoint identity.
