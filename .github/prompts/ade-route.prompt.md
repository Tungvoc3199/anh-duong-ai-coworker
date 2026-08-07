---
description: "Classify an ADE-OS request deterministically and select the smallest safe agent handoff."
name: ade-route
argument-hint: "Request to classify"
agent: ad-project
tools: [read, search, execute]
---
Classify `$ARGUMENTS` with `/home/thadc/AIOS/anh-duong-core/.venv/bin/python scripts/ade_os.py route -- "$ARGUMENTS"`. Report the selected route, matching evidence, and FACT / INFERENCE / UNKNOWN. Do not edit, restart, write runtime state, or claim closure. Hand off only to the selected agent when its preconditions are met.
