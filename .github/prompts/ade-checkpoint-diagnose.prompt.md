---
description: "Perform an evidence-led, read-only ADE checkpoint diagnosis and identify the smallest safe next handoff."
name: ade-checkpoint-diagnose
argument-hint: "Checkpoint or symptom"
agent: ad-diagnose
tools: [read, search, execute]
---
Diagnose `$ARGUMENTS` without editing, restarting, or writing runtime state. Check conflict scope, active modifications, runtime/source truth, health, logs, mounts, configuration, and read-only DB evidence as relevant. Return FACT / INFERENCE / UNKNOWN, reproduction status, evidence paths, affected boundary, and the smallest safe handoff. Escalate unresolved or multi-layer causes to Deep Debug.
