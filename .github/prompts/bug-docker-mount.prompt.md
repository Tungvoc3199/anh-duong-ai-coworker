---
description: "Diagnose Docker and WSL mount, bind mount, host/container file mismatch, Windows handle, and source/runtime divergence issues."
name: bug-docker-mount
argument-hint: "Mount, file, container, or divergence symptom"
agent: ad-deep-debug
tools: [read, search, execute]
---
Analyze `$ARGUMENTS` with read-only evidence. Map WSL `/mnt/c` and `/mnt/f`, bind mounts, source path versus runtime package path, container identity, file hashes, ownership and Windows-handle constraints. Do not mutate mounts, containers, or source. Return a source/runtime boundary table and the narrowest verified remediation.