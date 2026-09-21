# Ánh Dương Core — Agent Rules

## Runtime truth
- Canonical cross-agent contract: `docs/AGENT_RUNTIME_CONTRACT.md`.
- First action for every Ánh Dương task: run `/usr/local/libexec/anh-duong/runtime-truth`. A non-zero exit blocks mutation until diagnosed.
- Repository anchor: `/home/thadc/AIOS/anh-duong-core`; this is not proof that the root checkout is the active production source.
- Discover the active production release and Core port from the running process/effective systemd `ExecStart`; never hardcode a production port from README or a base unit.
- Runtime DB: `/home/thadc/.local/state/anh-duong-core/anh_duong.db`.
- Human-readable data mirror: `/mnt/f/AIOS/anh-duong-data`; checkpoints: `/mnt/f/AIOS/anh-duong-checkpoints`.
- Frozen release trees are immutable rollback/comparison anchors. Do not edit them to reconcile documentation.
- `/mnt/f/AIOS/anh-duong-core` is not an active runtime dependency.

## Evidence and safety
- Label claims as **FACT**, **INFERENCE**, **UNKNOWN**, or **PROPOSAL**. PASS needs evidence.
- Before a change: check active checkpoint, `git status --short`, runtime health, and relevant artifacts.
- Before every coding checkpoint, invoke `/usr/local/libexec/anh-duong/coding-preflight-controller` directly with the exact `--expected-workspace`, policy flags, and `-- git ...` operation. The static controller hard-binds the root-owned system guard installed from canonical `scripts/coding_preflight.sh`; that guard performs final validation and immediately `exec`s the requested Git operation in the same sanitized boundary; never invoke the guard, `bash`, or `env` directly. Require isolation/clean state for coding lanes and validate upstream/push target, exact push URL, and expected Git name/email at merge or push gates. Any non-zero exit is **BLOCKED** and must not be bypassed by mutating main or unrelated worktrees. `--destructive-cleanup` validates recovery/process evidence only and remains BLOCKED until an atomic cleanup executor proves the action boundary.
- One checkpoint is one complete objective. Do not alter an active checkpoint outside its approved scope.
- Preserve pre-existing changes; never stage, commit, reset, clean, stash, or revert unrelated work.
- Back up an existing persistent target before editing; record artifacts and rollback.
- Do not use destructive commands. Do not change providers, tokens, model routing, DB schema/migrations, or dependencies outside approved scope. Never expose secrets.
- Prefer the smallest verified repair, targeted tests before regression, and real E2E for runtime integrations.

## Runtime closure gate
- After any bot-impacting deploy, restart, or cutover, run `python3 scripts/verify_openclaw_core_path.py` and require PASS against the exact `ANH_DUONG_CORE_BASE_URL` configured inside the OpenClaw container.
- Closure evidence must keep local Core health/ready/DB, OpenClaw→Core authenticated prepare, and Telegram E2E as separate facts. A localhost or synthetic request is never Telegram E2E.
- A Telegram-impacting deployed release requires a fresh real Telegram inbound, Core prepare success, model response, Telegram outbound message ID, and clean post-test prepare logs before CLOSED.
- If post-cutover runtime verification fails, fail the closure gate and restore the recorded last-known-good release/config before any CLOSED claim.

## Workflow
1. Diagnose read-only.
2. Make one minimal, evidenced repair.
3. Escalate unclear or failed first repair to Deep Debug.
4. Obtain read-only Review before closure.
5. Do not claim PASS from file creation alone.
