---
description: "Trace a blocked request across preparation, route, capability, Task/Run execution, and notification."
name: bug-routing-blocked
argument-hint: "Blocked request identifier or symptoms"
agent: ad-diagnose
tools: [read, search, execute]
---
Trace `$ARGUMENTS` through: `input → prepare → route → capability → Task/Run → execution → notification`. Capture correlation IDs, state transitions, gate decisions, task/run status, retry and approval state. Keep DB access read-only. Return the first proven blocking boundary and a minimal next experiment or repair.