---
description: "Diagnose terminal exit 1, 2, 126, or 127, command-not-found, quoting, pipelines, shell and host/container mismatch."
name: bug-terminal-exit
argument-hint: "Command, exit code, and output"
agent: ad-diagnose
tools: [read, search, execute]
---
Diagnose `$ARGUMENTS` read-only. Identify shell, executable resolution, exit code, quoting and expansion, pipeline status, host/container context, GNU/BusyBox differences, and optional CLI availability. Do not install packages. Return the smallest reproducible command, FACT / INFERENCE / UNKNOWN, and a safe corrective path.