---
description: "Use when: diagnosing, fixing, reviewing, or closing an AIOS checkpoint."
applyTo: "**"
---
# Checkpoint workflow

Before any mutation, inspect the current checkpoint artifacts, `git status --short`, active modifications, and runtime health. Preserve unrelated work exactly.

Use this escalation: **Diagnose → Fix → Deep Debug when a first repair fails or the cause remains unclear → Review**. Work one complete objective at a time.

For a repair: capture evidence, back up every existing target, make the smallest scoped change, run targeted tests, then relevant regression and runtime/E2E verification. Record artifact paths, exact commands/results, diff scope, and rollback.

A closure requires proven gates, no secret disclosure, and review evidence. Do not invent a formal checkpoint ID; use the active roadmap/checkpoint identity.
