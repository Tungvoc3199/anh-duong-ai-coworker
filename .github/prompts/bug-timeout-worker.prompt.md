---
description: "Diagnose worker timeout, claim, lease, attempt, retry, idempotency, stuck-run, and notification behavior."
name: bug-timeout-worker
argument-hint: "Worker timeout or stuck-run evidence"
agent: ad-deep-debug
tools: [read, search, execute]
---
Analyze `$ARGUMENTS` read-only. Build a timestamped timeline of worker claims, lease expiry, attempts, retries, idempotency keys, run transitions, timeout budgets, cancellation, side effects, and notification outcomes. Keep DB access read-only. State proven versus uncertain side effects and propose one discriminating experiment.