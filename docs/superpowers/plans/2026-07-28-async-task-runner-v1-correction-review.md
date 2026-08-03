# Async Task Runner v1 Correction Review Implementation Plan

> **For agentic workers:** Follow this plan task by task with
> `superpowers:executing-plans`; every production change must be preceded by a
> failing behavior test and every completion claim by fresh verification.

**Goal:** Correct Async Task Runner v1 auditability, cancellation safety,
filtering, shutdown admission control, and concurrent idempotency before any
runtime installation.

**Architecture:** Keep the existing SQLite-backed Task/Run model and the
append-only JSONL `AuditWriter`. Inject the writer into
`AsyncTaskRepository`, emit only bounded metadata from state-changing
operations, and rely on the writer's recursive `SecretRedactor`. Serialize
explicit-key creation with SQLite `BEGIN IMMEDIATE` before the idempotency
lookup so concurrent HTTP requests observe one committed Task/Run pair. Keep
OpenClaw execution and notification strictly on the existing HTTP Gateway.

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy 2, SQLite, Pydantic 2,
pytest/httpx, Ruff, Mypy, Alembic.

**Safety constraints:** Do not migrate the runtime database, restart
Core/OpenClaw/Docker, modify OpenClaw configuration, send real Telegram
messages, alter credentials/models/providers, or deploy.

---

## Task 1: RED tests for audit events and secret redaction

**Files:**

- Create: `tests/integration/test_async_task_audit.py`
- Modify: `tests/integration/test_async_task_worker.py`
- Modify: `tests/integration/test_async_task_recovery.py`
- Modify: `tests/integration/test_notification_worker.py`

1. Add repository lifecycle tests that exercise created, claimed,
   retry-scheduled, completed, failed, blocked, and cancelled states with a
   real temporary `AuditWriter`.
2. Add stale recovery coverage for `async_run.recovered`, including a blocked
   recovery emitting both recovery and blocked terminal facts.
3. Add notifier success/final-failure coverage for
   `async_notification.sent` and `async_notification.failed`.
4. Put bearer/assignment-shaped secrets in request and error values; assert
   the raw audit JSONL contains no secret while its integrity check passes.
5. Run only these tests and confirm they fail because the async event stream
   does not yet exist.

## Task 2: GREEN append-only Async Run audit stream

**Files:**

- Create: `app/async_tasks/audit.py`
- Modify: `app/async_tasks/repository.py`
- Modify: `app/async_tasks/worker.py`
- Modify: `app/async_tasks/recovery.py`
- Modify: `app/async_tasks/notification.py`
- Modify: `app/async_tasks/__init__.py`
- Modify: `app/main.py`

1. Add one bounded audit helper that builds `AuditEvent` from an
   `AsyncTaskRun`, extracts only project identity from already-redacted request
   JSON, hashes the idempotency key, and never copies goal, raw request,
   authorization, or token fields into the payload.
2. Add optional `AuditWriter` injection to `AsyncTaskRepository` and emit the
   required lifecycle event immediately after each successful state mutation.
3. Propagate the writer through API, execution worker, recovery, and
   notification worker construction.
4. Emit notification success only for `SENT`, and failure only for terminal
   notification `FAILED`; retryable delivery attempts remain state-only.
5. Run the audit-focused tests until green, then run adjacent worker/recovery/
   notifier suites.

## Task 3: RED then GREEN cancellation safety

**Files:**

- Modify: `tests/integration/test_async_task_api.py`
- Modify: `tests/integration/test_async_task_repository.py`
- Modify: `app/async_tasks/models.py`
- Modify: `app/async_tasks/repository.py`
- Modify: `app/api/async_tasks.py`

1. Add tests for immediate cancel of `pending` and `retry_wait`, idempotent
   `cancelled`, and HTTP 409 with unchanged state for `claimed`, `running`,
   `verifying`, and `completed`.
2. Confirm the active-state cases fail against the current API.
3. Remove cancellation transitions from active execution states and restrict
   repository cancellation to `pending`/`retry_wait`; retain an idempotent
   return for `cancelled`.
4. Let the API translate all unsafe states to HTTP 409 before changing the
   Task or queuing a notification.
5. Run cancellation-focused tests until green.

## Task 4: RED then GREEN API filter and admission control

**Files:**

- Modify: `tests/integration/test_async_task_api.py`
- Modify: `app/async_tasks/repository.py`
- Modify: `app/api/async_tasks.py`
- Modify: `docs/ASYNC_TASK_RUNNER_V1.md`

1. Add a list test proving `GET /api/async-tasks?task_id=task_...` returns only
   the requested Task's run.
2. Add a POST test that flips `app.state.accepting_async_tasks` to false and
   proves HTTP 503 with no Task/Run creation.
3. Confirm both tests fail for the expected missing behaviors.
4. Add the optional repository/API `task_id` filter and fail-closed POST state
   gate.
5. Document list filtering, admission behavior, and safe-cancel rules.

## Task 5: RED then GREEN concurrent HTTP idempotency

**Files:**

- Modify: `tests/integration/test_async_task_api.py`
- Modify: `app/async_tasks/repository.py`
- Modify: `app/async_tasks/service.py`

1. Add a real concurrent ASGI test using two requests with the same explicit
   idempotency key and separate database sessions.
2. Assert both responses are 202 with the same Task/Run IDs and the database
   contains exactly one Task and one Run.
3. Confirm the pre-fix behavior reproduces either a unique-conflict 500 or
   duplicate orphan Task risk.
4. Add a repository creation lock that issues SQLite `BEGIN IMMEDIATE` only
   for a fresh transaction; acquire it before the first idempotency lookup.
5. Preserve the existing unique constraint as the final database invariant
   and rerun the concurrent test repeatedly.

## Task 6: Full verification and corrected handoff

**Files:**

- Modify: `scripts/package_async_task_runner_v1.py`
- Modify: `docs/ASYNC_TASK_RUNNER_V1.md`
- Update externally: `F:\AIOS\anh-duong-data\deliverables\anh-duong-core-async-task-runner-v1.zip`
- Update externally: `F:\AIOS\anh-duong-data\deliverables\anh-duong-core-async-task-runner-v1.md`
- Update externally: `F:\AIOS\anh-duong-data\chat-handoff\async-task-runner-v1-autonomous-final-report.md`

1. Run targeted correction tests, then full Pytest and the security suite.
2. Run full Ruff, changed-Python-file Mypy, and Compileall.
3. Run Alembic `0003 -> 0002 -> 0003` against a fresh temporary SQLite
   database and inspect the expected table after each boundary.
4. Update the packaging manifest, measured test counts, corrected status, and
   an explicit overwrite flag for the user-authorized artifact replacement.
5. Rebuild the ZIP and Markdown atomically; write the final report with
   `VERIFIED_COMPLETE_CORRECTED` as its first line.
6. Recompute and independently verify SHA256 values and inspect ZIP members.
7. Re-run the most relevant tests after packaging-script changes and report
   exact results, changed files, remaining risk, and operator-only next steps.

There is no Git checkout in this workspace, so branch/worktree creation and
commits are not available. All work remains directly inspectable in the
user-designated workspace and in the generated overlay.
