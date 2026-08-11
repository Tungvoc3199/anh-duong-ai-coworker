---
description: "Diagnose pytest, Ruff, Mypy, compileall, flaky, integration, and pre-existing regression failures without weakening tests."
name: bug-regression
argument-hint: "Failing command, test, or regression evidence"
agent: ad-diagnose
tools: [read, search, execute]
---
Diagnose `$ARGUMENTS`. Reproduce the narrowest failing check, classify environment/pre-existing/flaky/product causes, inspect affected code and test contracts, and preserve the test signal. Never weaken, skip, or delete a test to hide a defect. Return exact evidence, minimal cause, and the smallest safe repair path.