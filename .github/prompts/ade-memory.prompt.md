---
description: "Query approved external runtime memory through ADE-OS using a supplied read-only CLI and fail closed on unavailable evidence."
name: ade-memory
argument-hint: "Read-only memory CLI arguments"
agent: ad-diagnose
tools: [read, search, execute]
---
Use the ADE memory command only with the explicitly supplied read-only CLI arguments in `$ARGUMENTS`. Preserve redacted evidence and report FACT / INFERENCE / UNKNOWN. If the CLI cannot run, times out, or fails, report memory as unavailable; do not query or write the runtime DB, call providers, or use unbounded shell execution.
