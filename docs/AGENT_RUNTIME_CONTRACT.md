# Ánh Dương — Agent Runtime Contract

This file is the canonical operating contract for agents working on Ánh Dương.
Static path or port values in historical artifacts never override fresh runtime evidence.

## Mandatory first action

Before diagnosis, coding, deployment, or claims about production, run:

```bash
/usr/local/libexec/anh-duong/runtime-truth
```

If the installed launcher is unavailable, run the repository copy from the current worktree:

```bash
"$(git rev-parse --show-toplevel)/scripts/runtime_truth.sh"
```

A non-zero exit means runtime truth is not clean enough for mutation. Diagnose first.

## Path semantics

- Canonical repository anchor: `/home/thadc/AIOS/anh-duong-core`.
- Isolated coding worktrees: `/home/thadc/AIOS/worktrees/*` or explicitly registered Git worktrees.
- Production release: discover from `anh-duong-runtime-truth`; never assume the repository anchor is live.
- Runtime SQLite DB: `/home/thadc/.local/state/anh-duong-core/anh_duong.db`.
- Human-readable data mirror: `/mnt/f/AIOS/anh-duong-data`.
- Checkpoint/evidence root: `/mnt/f/AIOS/anh-duong-checkpoints`.
## Runtime precedence

Use this evidence order when facts conflict:

1. Running process cwd and effective systemd properties.
2. `/health`, `/ready`, DB state, container state, and effective environment.
3. Current checkpoint evidence.
4. Current branch/worktree source.
5. README, generated indexes, old releases, and historical artifacts.

Never infer the active Core port from a README or base unit file. The effective systemd
drop-in may override it. The runtime truth command discovers the active port from
`ExecStart` and probes that exact endpoint.

Frozen production releases are immutable comparison/rollback anchors. Do not edit a
release tree to make its embedded documentation look current.

## Mutation rules

- Start read-only.
- Identify the exact worktree, branch, checkpoint, and production release.
- Preserve unrelated tracked and untracked changes.
- Never reset, clean, stash, revert, or overwrite unrelated work.
- Use an isolated worktree for coding.
- Trace root cause before editing.
- Make the smallest scoped patch.
- Test targeted behavior before broader regression.
- Do not deploy/restart production before the owner deploy gate.
## Cross-agent bootstrap

The following agent entry files must all point back to this contract and runtime probe:

- `AGENTS.md` — Codex/OpenAI-style agents.
- `CLAUDE.md` — Claude Code.
- `GEMINI.md` — Gemini CLI / Gemini-based coding agents.
- `.github/copilot-instructions.md` — GitHub Copilot.
- `.github/instructions/runtime-truth.instructions.md` — VS Code/ADE runtime rule.

Workspace-level bootstrap files under both `/home/thadc/AIOS` and `/mnt/f/AIOS`
provide the same first-step rule so an agent launched above the repository still
discovers the contract.

## Portable repository commands

When a command must address the current worktree, derive it instead of hardcoding
`/home/thadc/AIOS/anh-duong-core`:

```bash
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
```

Machine-level runtime paths are intentionally absolute because they identify the
deployed service, DB, data mirror, and evidence store.
## Closure requirements

Before claiming PASS/CLOSED:

- `anh-duong-runtime-truth` returns `RUNTIME_TRUTH=PASS`.
- Relevant targeted tests pass.
- Runtime-impacting changes run the required Core/OpenClaw/Telegram verification.
- Documentation/configuration paths agree with effective runtime truth.
- `git status --short` is clean or every remaining delta is explicitly classified.
- Closure evidence records the exact commit, worktree, production release, and probes.

Historical artifacts are evidence and are not rewritten merely because they contain
old paths or ports. See `docs/LEGACY_RUNTIME_REFERENCES.md` before using any old
checkpoint-specific deployment or verification helper.
