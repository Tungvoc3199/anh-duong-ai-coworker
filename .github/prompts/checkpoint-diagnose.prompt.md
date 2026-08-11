---
description: "Read-only checkpoint diagnosis: inventory, reproduction, evidence, and root cause."
name: checkpoint-diagnose
argument-hint: "Checkpoint or symptom to diagnose"
agent: ad-diagnose
tools: [read, search, execute]
---
Diagnose `$ARGUMENTS` without editing, restarting, or writing runtime state.

1. Check checkpoint conflicts, active modifications, source/runtime truth, health, logs, config, DB and mounts as relevant.
2. Reproduce safely or identify why reproduction is blocked.
3. Collect one concise evidence log in the artifacts directory when output is long.
4. Return FACT / INFERENCE / UNKNOWN, a minimal root-cause conclusion, affected boundaries, and the smallest safe next step.

Do not propose a repair as proven until evidence isolates the cause.