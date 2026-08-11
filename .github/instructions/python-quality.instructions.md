---
description: "Use when: editing Python code, tests, or Python automation in this repository."
applyTo: "**/*.py"
---
# Python quality

Use standard library where sufficient. Keep changes typed, small, deterministic, and testable. Handle I/O and subprocess failures explicitly; use bounded timeouts. Do not log secrets.

Before declaring a Python change valid, run `/home/thadc/AIOS/anh-duong-core/.venv/bin/python -m compileall` for changed Python and the most targeted pytest first. Run Ruff/Mypy only when configured/available; report pre-existing failures separately. Do not weaken tests to hide defects.
