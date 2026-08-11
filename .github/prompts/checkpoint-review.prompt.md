---
description: "Strict read-only checkpoint review: scope, diff, tests, secrets, rollback, runtime evidence, and closure gates."
name: checkpoint-review
argument-hint: "Checkpoint or diff to review"
agent: ad-review
tools: [read, search, execute]
---
Review `$ARGUMENTS` strictly read-only. Verify scope, unrelated-change preservation, diff minimality, targeted and regression evidence, runtime/E2E proof, secrets, backups, rollback, and closure gates. Return exactly one final result: **PASS**, **CHANGES_REQUIRED**, or **BLOCKED**, with evidence. For CHANGES_REQUIRED, name the smallest required action and hand off to `ad-fix`.