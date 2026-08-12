# Agent Final Response Resilience — 2026-08-12

## Current verdict

- Regression evidence from Telegram: CONFIRMED — workflow ACK was followed by `OpenClaw returned an invalid execution result contract.`
- Root cause: CONFIRMED against GitHub `main` baseline `9e44adfde276ef687dfc86087e394876f83b77b0`.
- Source repair: VERIFIED on commit `55be19163bb0419979d8c1bc664f74e8ab8ac849`.
- GitHub Actions full behavioral regression: PASS, run `31619105323`.
- Clean publication source commit prepared: `e4ae93677d83e807e5021eacb8018a8932647295`.
- Production runtime activation: NOT YET VERIFIED.
- Real Telegram production E2E after this repair: NOT YET VERIFIED.
- Checkpoint closure: OPEN until production E2E proves `ACK -> agent work -> final delivered`.

## Root cause

`OpenClawExecutor` coupled the agent's useful final answer to optional execution metadata under one strict Pydantic contract. If the model returned useful JSON whose metadata shape varied from the expected schema, `OpenClawExecutionResult.model_validate(...)` raised a validation error. The executor converted that to `invalid_response_contract`; the worker then terminalized the run and the Telegram notifier sent the internal contract error instead of the useful final answer.

The behavior was inconsistent because plain non-JSON output was already converted to a completed result, while structured JSON was rejected more aggressively.

## Repair

1. Keep transport and OpenClaw response-envelope failures fail-closed.
2. Normalize model-produced result content before the typed result boundary.
3. Preserve a user-facing final from `summary`, `answer`, `final_answer`, `message`, `response`, `text`, or `content`, including nested `result` objects.
4. Normalize common outcome aliases such as `success`, `succeeded`, `done`, `ok`, error states, and approval-required states.
5. Preserve generic `artifacts` and `verification` dictionaries when they only partially resemble a known typed schema.
6. Normalize non-critical metadata such as `files_changed`, `commands_run`, `tests`, and `duration_ms` instead of rejecting the final answer.
7. Treat an explicitly unknown outcome conservatively as `failed` while still preserving the final user-facing text.
8. If typed validation still fails after normalization, create a terminal failed result with the preserved summary instead of emitting `invalid_response_contract` for model-produced result metadata.
9. Strengthen the execution instruction so a final user-facing answer is mandatory and metadata is secondary.
10. Redact the normalized result payload before persistence so the broader accepted metadata shapes do not create a secret-leak path.

## Fresh verification — GitHub Actions run 31619105323

Verified commit: `55be19163bb0419979d8c1bc664f74e8ab8ac849`.

Blocking gates:

- Full Python behavioral regression: `420 passed in 5.86s`.
- Scoped Ruff on final-response source and tests: PASS (`All checks passed!`).
- Strict app mypy with only the previously known `app.async_tasks.recovery` `arg-type` debt baselined: PASS, `66 source files`, zero new issues.
- `python -m compileall -q app`: PASS.
- Full OpenClaw plugin regression: `62 passed`, `0 failed`.
- GitHub Actions job conclusion: SUCCESS.

The metadata-variation regression matrix covers success/done aliases, failure aliases, approval-required states, missing outcome, nested result objects, scalar/list/object metadata variants, unknown provider-specific outcomes, malformed known-looking workflow metadata, and secret redaction. In every covered model-result variation, a useful final is preserved rather than replaced by `invalid_response_contract`.

Non-blocking pre-existing repository debt observed by diagnostics:

- Repository-wide Ruff baseline: 156 pre-existing findings outside this scoped repair.
- Repository-wide mypy baseline: 3 pre-existing findings in `scripts/ade_os/core.py`, `app/async_tasks/recovery.py`, and `scripts/agent/validate_changed.py`.

These diagnostics are outside the final-response repair scope and were not modified.

## Production safety / remaining closure gate

No production host file, systemd service, OpenClaw runtime, DB/schema/migration, provider, token, model routing, cache, or Telegram configuration was changed by the CI verification.

Closure requires fresh production evidence after activating the verified source in `/home/thadc/AIOS/anh-duong-core`:

`workflow request -> ACK visible -> agent execution -> terminal final delivered to Telegram`

The temporary ACK may be cleaned up only after final notification is confirmed sent. The checkpoint must remain OPEN if the final is missing, if `invalid_response_contract` replaces a useful final, or if runtime activation cannot be proven.
