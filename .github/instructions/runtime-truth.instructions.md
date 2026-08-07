---
description: "Use when: working anywhere in Ánh Dương Core and runtime facts affect the task."
applyTo: "**"
---
# Runtime truth

- Active source is `/home/thadc/AIOS/anh-duong-core`; never repair `/mnt/f/AIOS/anh-duong-core` as if it were live.
- Runtime DB is `/home/thadc/.local/state/anh-duong-core/anh_duong.db`.
- Service is `anh-duong-core.service`; active endpoint is `http://127.0.0.1:8790`, not port 8000.
- Record long diagnostic output under `/mnt/f/AIOS/anh-duong-checkpoints`.
- Treat service health, logs, DB state, mounts, and active container configuration as stronger evidence than assumptions or stale docs.
- State FACT / INFERENCE / UNKNOWN separately. Redact credentials and authorization values.
