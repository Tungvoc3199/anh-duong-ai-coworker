# Ánh Dương Core — Agent Rules

## Runtime truth
- Active source: `/home/thadc/AIOS/anh-duong-core`; runtime DB: `/home/thadc/.local/state/anh-duong-core/anh_duong.db`.
- Artifacts: `/mnt/f/AIOS/anh-duong-checkpoints`; port: `8790`.
- `/mnt/f/AIOS/anh-duong-core` is not an active runtime dependency.

## Evidence and safety
- Label claims as **FACT**, **INFERENCE**, **UNKNOWN**, or **PROPOSAL**. PASS needs evidence.
- Before a change: check active checkpoint, `git status --short`, runtime health, and relevant artifacts.
- One checkpoint is one complete objective. Do not alter an active checkpoint outside its approved scope.
- Preserve pre-existing changes; never stage, commit, reset, clean, stash, or revert unrelated work.
- Back up an existing persistent target before editing; record artifacts and rollback.
- Do not use destructive commands. Do not change providers, tokens, model routing, DB schema/migrations, or dependencies outside approved scope. Never expose secrets.
- Prefer the smallest verified repair, targeted tests before regression, and real E2E for runtime integrations.

## Workflow
1. Diagnose read-only.
2. Make one minimal, evidenced repair.
3. Escalate unclear or failed first repair to Deep Debug.
4. Obtain read-only Review before closure.
5. Do not claim PASS from file creation alone.

## Runtime/Git closure consistency
- Runtime-affecting changes are not CLOSED until deployed runtime, tracked configuration, and Git commit are mutually consistent.
- No undocumented host-only configuration drift is allowed.
- Before closure, compare the effective deployed runtime configuration against the tracked repository representation and resolve any drift inside the checkpoint scope.
- A checkpoint is not CLOSED merely because a local commit exists; verify the intended scoped commit is present on the authoritative GitHub branch and contains the runtime-affecting changes.
- Secrets and host-local secret values must not be committed. Track only safe configuration/templates needed to reconstruct the runtime shape.

## Automatic commit for verified fixes
- For every bug/error repair, once the scoped fix is verified PASS, commit it automatically without asking the user for separate commit approval.
- Stage and commit only the exact files belonging to the verified fix plus its closure/evidence artifacts; never include unrelated dirty files.
- Do not re-run an already-passed verification solely because commit mechanics failed; fix the Git/permission/worktree issue and continue the same commit operation.
- If the normal working tree cannot safely commit because of locks, permissions, divergence, or unrelated dirty state, use a safe isolated worktree or other non-destructive Git path rather than mixing or discarding existing work.
- This standing approval covers Git commit of verified fixes. It does not by itself authorize destructive operations, production deploy/restart, provider/token/model changes, DB migration, or other protected actions.

## User-facing prompt minimization
- One checkpoint = one complete objective.
- Give the user only one concise command or prompt per checkpoint.
- Do not expose internal cross-project gates, safety gates, verification checklists, test matrices, review procedures, or evidence requirements in the user-facing prompt unless explicitly requested.
- Perform those checks internally and autonomously.
- Write long diagnostics and evidence to artifacts/logs instead of pasting them into chat.
- User-facing completion output should contain only: PASS/FAIL, root cause if failed, artifact path, and next action.
- Never require the user to manually inspect long scripts/logs or perform multi-step verification that the agent can do itself.
