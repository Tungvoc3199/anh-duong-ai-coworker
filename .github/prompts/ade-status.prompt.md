---
description: "Summarize ADE-OS project status, active checkpoint evidence, modifications, and runtime health without modifying state."
name: ade-status
argument-hint: "Project, checkpoint, or status question"
agent: ad-project
tools: [read, search, execute]
---
Assess `$ARGUMENTS` read-only. Inspect configured ADE project data, active checkpoint artifacts, `git status --short`, and runtime health when relevant. Return FACT / INFERENCE / UNKNOWN, current gate, evidence paths, preserved pre-existing modifications, and the smallest safe handoff. Do not edit, restart, write runtime state, or claim a checkpoint is closed.
