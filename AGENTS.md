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

## User-facing prompt minimization
- One checkpoint = one complete objective.
- Give the user only one concise command or prompt per checkpoint.
- Do not expose internal cross-project gates, safety gates, verification checklists, test matrices, review procedures, or evidence requirements in the user-facing prompt unless explicitly requested.
- Perform those checks internally and autonomously.
- Write long diagnostics and evidence to artifacts/logs instead of pasting them into chat.
- User-facing completion output should contain only: PASS/FAIL, root cause if failed, artifact path, and next action.
- Never require the user to manually inspect long scripts/logs or perform multi-step verification that the agent can do itself.
