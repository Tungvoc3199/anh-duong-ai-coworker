---
description: "Deep debugging for nondeterministic, multi-layer, timeout, race, state, or source/runtime divergence failures."
name: checkpoint-deep
argument-hint: "Hard bug or failed repair evidence"
agent: ad-deep-debug
tools: [read, search, execute]
---
Deep-debug `$ARGUMENTS` read-only first. Build a timeline and component-boundary map. State explicit hypotheses, test one hypothesis at a time, preserve negative evidence, and distinguish source from active runtime. Return only a proven root cause or BLOCKED with the next discriminating experiment. Hand the smallest proven repair back to `ad-fix`.