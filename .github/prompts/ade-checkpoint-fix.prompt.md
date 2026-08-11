---
description: "Apply one minimal approved ADE checkpoint repair with backup, validation, rollback, and review-ready evidence."
name: ade-checkpoint-fix
argument-hint: "Proven cause and approved repair scope"
agent: ad-fix
tools: [read, search, execute, edit]
---
Repair only the proven, approved scope in `$ARGUMENTS`. Before writing, recheck conflict gate, `git status --short`, health, active modifications, and runtime truth; back up every existing persistent target with a UTC suffix. Make one narrow repair, run targeted tests before relevant regression and runtime/E2E checks, and record diff, evidence paths, and rollback. Do not change credentials, provider/model routing, runtime DB/migrations, dependencies, or unrelated work. Hand off to Deep Debug after one failed repair or unclear cause, and to Review only with PASS-ready evidence.
