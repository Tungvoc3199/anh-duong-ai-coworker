# Ánh Dương AI Coworker Core

Phase 0–1 foundation for the Python “brain” service.

## Runtime truth

Do not infer production from the checkout path or a hardcoded port. Before operational
work, run:

```bash
/usr/local/libexec/anh-duong/runtime-truth
```

The command discovers the effective systemd release and port, probes `/health` and
`/ready`, and verifies the runtime data paths without exposing secrets.

Stable machine-level paths:

- Canonical repository anchor: `/home/thadc/AIOS/anh-duong-core`
- SQLite DB: `/home/thadc/.local/state/anh-duong-core/anh_duong.db`
- Human-readable data mirror: `/mnt/f/AIOS/anh-duong-data`
- Checkpoint evidence: `/mnt/f/AIOS/anh-duong-checkpoints`

The active production release is a separate immutable release directory and must be
discovered from runtime truth.
## Agent contract

All coding agents must read `docs/AGENT_RUNTIME_CONTRACT.md`. Tool-specific entry
files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, and Copilot instructions) point to
the same contract.

## Setup

From any registered checkout/worktree:

```bash
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
./scripts/setup.sh
cp .env.example ~/.config/anh-duong-core/.env
./scripts/init_db.sh
./scripts/test.sh
```

SQLite stays on the Linux filesystem. The human-readable mirror is stored on F:.

## Local development

Port `8790` is the repository's local-development default only. It is not a
production truth value:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8790
```
## Production health

Use the runtime probe instead of copying a port from this README:

```bash
/usr/local/libexec/anh-duong/runtime-truth
```

A clean production state reports `RUNTIME_TRUTH=PASS`. A non-zero exit requires
diagnosis before mutation or deployment.
