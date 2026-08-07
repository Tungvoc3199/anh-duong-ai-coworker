---
description: "Verified checkpoint repair: conflict check, backup, minimal fix, tests, E2E, and review handoff."
name: checkpoint-fix
argument-hint: "Approved repair objective"
agent: ad-fix
tools: [read, search, edit, execute, todo]
---
Repair `$ARGUMENTS` only after verifying the conflict gate and approved scope.

Back up existing targets with UTC suffixes, preserve unrelated modifications, make one minimal evidenced change, run targeted tests before regression, and run runtime/E2E checks where integration is affected. Record diff, test, artifact, and rollback evidence. If the first repair cycle fails or cause becomes unclear, hand off to `ad-deep-debug`. On PASS-ready evidence, hand off to read-only `ad-review`.