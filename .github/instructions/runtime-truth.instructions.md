---
description: "Use when: working anywhere in Ánh Dương Core and runtime facts affect the task."
applyTo: "**"
---
# Runtime truth

- Read `docs/AGENT_RUNTIME_CONTRACT.md`.
- Run `/usr/local/libexec/anh-duong/runtime-truth` before any mutation or production claim.
- The repository anchor `/home/thadc/AIOS/anh-duong-core` is not proof of the active production release.
- Discover the active release and Core endpoint from the running process/effective systemd configuration; never assume port 8790, 8792, or 8000.
- Runtime DB is `/home/thadc/.local/state/anh-duong-core/anh_duong.db`.
- Human-readable data mirror is `/mnt/f/AIOS/anh-duong-data`.
- Long diagnostic/checkpoint evidence belongs under `/mnt/f/AIOS/anh-duong-checkpoints`.
- Frozen releases are immutable. Repair only an isolated coding worktree, never a release tree.
- Treat process cwd, effective systemd properties, health/ready, DB, mounts, and active container state as stronger evidence than static docs.
- State FACT / INFERENCE / UNKNOWN separately. Redact credentials and authorization values.
