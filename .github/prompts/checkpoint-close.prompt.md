---
description: "Create a checkpoint closure record only after all objective gates have evidenced PASS."
name: checkpoint-close
argument-hint: "Completed checkpoint"
agent: ad-orchestrator
tools: [read, search, execute]
---
Assess whether `$ARGUMENTS` may be closed. Do not edit application code. Require: conflict resolution, scoped diff, preserved unrelated work, tests, runtime/E2E evidence when applicable, review PASS, artifact paths, backup inventory, and rollback. If any gate lacks evidence, return BLOCKED with the missing proof. Never create a closure from file creation or health status alone.