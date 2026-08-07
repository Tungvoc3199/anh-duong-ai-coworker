---
description: "Conduct a strict read-only ADE checkpoint review and decide PASS, CHANGES_REQUIRED, or BLOCKED from evidence."
name: ade-checkpoint-review
argument-hint: "Checkpoint or repair to review"
agent: ad-review
tools: [read, search]
---
Review `$ARGUMENTS` read-only. Verify scope, minimal diff, preserved unrelated work, secrets handling, backups, rollback, targeted and regression tests, runtime/E2E evidence when applicable, and active-checkpoint compliance. Return exactly **PASS**, **CHANGES_REQUIRED**, or **BLOCKED** with cited evidence. PASS is forbidden unless every applicable closure gate is evidenced. For CHANGES_REQUIRED, hand off only the smallest required repair.
