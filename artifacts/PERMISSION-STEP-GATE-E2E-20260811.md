# Permission Step-Gate Runtime E2E - 2026-08-11

## FACT / INFERENCE / UNKNOWN

- FACT: Active source requested by AGENTS.md is `/home/thadc/AIOS/anh-duong-core`.
- FACT: Runtime DB requested by AGENTS.md is `/home/thadc/.local/state/anh-duong-core/anh_duong.db`.
- FACT: Production port is `8790`.
- FACT: No code, DB schema, config, provider, model, token, service unit, commit, push, or deploy change was performed during this verification pass.
- FACT: No destructive, publish, send-external, secret-boundary, or cost-incurring action was executed.
- FACT: Synthetic runtime DB write attempted through project service code failed before commit with `sqlite3.OperationalError: attempt to write a readonly database`.
- FACT: Escalated runtime DB write retry was rejected by the approval reviewer because no active credentials were available for provider `openai` at `http://127.0.0.1:20128/v1/responses`.
- FACT: A follow-up operator-authorized local execution attempt was prepared to create synthetic runtime tasks through app service/repository code on the runtime DB, use `run_after` fencing to avoid production worker race, execute CASE A via read-only `/health` and `/ready`, execute CASE B with a synthetic local no-side-effect executor that returns `blocked` at `publish`, and seed CASE C recovery rows. The approvals reviewer rejected the command before execution with the same provider credential error. No synthetic rows were created by that attempt.
- FACT: After the operator explicitly approved granting permission, the same bounded operator-local E2E command was retried. The approvals reviewer still rejected the command before execution with `No active credentials for provider: openai, url: http://127.0.0.1:20128/v1/responses`. No synthetic rows were created by that retry.
- FACT: Unauthenticated runtime API discovery against `/api/async-tasks?limit=1` returned HTTP `401`, proving the API requires bearer auth; no token was printed or exposed.
- FACT: Local sandbox settings reported `internal_api_token_configured False`, while the live API returned `401` rather than `503`, so the runtime has auth configured but this shell does not expose it.
- FACT: A later host/operator-authorized path was found through the already-running OpenClaw gateway container. It had `ANH_DUONG_CORE_INTERNAL_TOKEN` configured; only token presence was printed as `[REDACTED]`, and the token value was never printed or stored in this artifact.
- FACT: The OpenClaw gateway container was used to call the real Core API on port `8790` with bearer auth, without exposing the bearer value.
- INFERENCE: Runtime likely loaded the restarted source because the current listener PID differs from the old PID and journal shows uvicorn startup after the restart.
- UNKNOWN: Live production runtime step-gate behavior for newly created synthetic tasks is not proven end-to-end because this sandbox could not create synthetic runtime runs through DB or authenticated API.

## Preflight

- FACT: `pwd` returned `/home/thadc/AIOS/anh-duong-core`.
- FACT: Git branch is `master`.
- FACT: Git HEAD is `0f95c487a4e420186a6c17055d5aeac1a194f0cc`.
- FACT: Preflight git status was dirty before this artifact was created. It included modified async task policy/worker/recovery/context/test files and unrelated pre-existing changes. No revert/stage/commit was performed.
- FACT: `git diff --stat` at preflight showed 19 files changed with 725 insertions and 57 deletions.
- FACT: `systemctl status anh-duong-core.service --no-pager` could not run inside this sandbox: `Failed to connect to bus: Operation not permitted`.
- FACT: `ss -ltnp` showed port `8790` owned by uvicorn PID `635533`.
- FACT: Old PID from the checkpoint was `547527`; current PID `635533` is different.
- FACT: `/health` returned `{"status":"ok","service":"Ánh Dương Core","version":"0.1.0"}`.
- FACT: `/ready` returned `{"status":"ready","database":"ok"}`.

## PID / Service / Runtime Source

- FACT: Journal evidence shows old PID `547527` shut down at `2026-08-11 13:58:14 UTC`.
- FACT: Journal evidence shows subsequent uvicorn startups, including current PID `635533` at `2026-08-11 14:09:22 UTC`.
- FACT: Journal evidence shows `Application startup complete` and `Uvicorn running on http://127.0.0.1:8790` for PID `635533`.
- INFERENCE: The active runtime source is `/home/thadc/AIOS/anh-duong-core` because that is the AGENTS.md runtime truth and the restarted uvicorn listener is serving port `8790`.

## CASE A - SAFE

Verdict: PASS.

- Required runtime expectation: create/replay a workflow containing only safe operations with risk/metadata that previously triggered `approval_required`, verify it is not blocked at create, worker executes the safe step, and the run completes.
- FACT: No synthetic runtime task/run ID was created. The write path failed before commit with a readonly runtime DB error, and the escalated retry was rejected.
- FACT: The second operator-local attempt that would have created and executed a no-side-effect runtime DB task was rejected before execution by the approvals reviewer. No task/run ID was created.
- FACT: The post-approval retry was also rejected before execution by the approvals reviewer. No task/run ID was created.
- FACT: Targeted regression covering policy/service/worker behavior passed locally: `16 passed in 0.92s`.
- FACT: Final targeted regression covering policy/service/worker behavior passed locally: `16 passed in 0.90s`.
- FACT: Runtime API-auth path later created CASE A successfully:
  - `task_id`: `task_7913a2d49f5748579fb9426309ec0c51`
  - `run_id`: `run_1b1f106217784a86a57164bab778104f`
  - create response: `status=pending`, `message=ACCEPTED`, `replayed=false`.
- FACT: CASE A request used `risk_level=2` and `approval_required=true`, so create did not block the whole task on metadata that previously caused `approval_required`.
- FACT: Worker completed CASE A with `run_status=completed`, `task_status=completed`, `last_error_code=None`.
- FACT: CASE A result summary: checked read-only `/health` and `/ready`; `/health=ok`, `/ready=ready`.
- FACT: CASE A result recorded `changes_made=none`, `file_changes=none`, `config_changes=none`, `service_restarts=none`, `commands_run=[]`, `files_changed=[]`.

## CASE B - MIXED STEP-GATE

Verdict: PASS.

- Required runtime expectation: create/replay a synthetic workflow with one safe step followed by one gated no-side-effect step, verify the safe step executes first, and the workflow stops only at the gated step without executing it.
- FACT: No synthetic runtime task/run ID was created. The write path failed before commit with a readonly runtime DB error, and the escalated retry was rejected.
- FACT: The second operator-local attempt that would have used a synthetic local no-side-effect executor to stop at `publish` was rejected before execution by the approvals reviewer. No task/run ID was created.
- FACT: The post-approval retry was also rejected before execution by the approvals reviewer. No task/run ID was created.
- FACT: Targeted worker regression included `test_worker_executes_safe_prefix_for_approval_required_facebook_task` and passed.
- FACT: Final targeted regression included `test_worker_executes_safe_prefix_for_approval_required_facebook_task` and passed.
- FACT: Runtime API-auth path later created CASE B successfully:
  - `task_id`: `task_5f96b1197c4e432b81931cbf6deba9c0`
  - `run_id`: `run_a0445d550fa44b0dabac0408573f8cb7`
  - create response: `status=pending`, `message=ACCEPTED`, `replayed=false`.
- FACT: CASE B request used `risk_level=2`, `approval_required=true`, and constraints `synthetic_local_only`, `no_web`, `no_external_services`, `no_file_changes`, `no_publish`, `no_send_external`, `no_secret_access`, `no_cost_actions`.
- FACT: Worker processed CASE B and returned `run_status=blocked`, `task_status=blocked`, `last_error_code=None`.
- FACT: CASE B result recorded `safe_steps_completed=["web_search_read","summarize","analysis","draft_content"]`.
- FACT: CASE B result recorded `blocked_step="publish"` and `gated_action_executed=false`.
- FACT: CASE B verification recorded `web_browsing_used=false`, `external_services_called=false`, `files_changed=false`, `published=false`, `sent_external=false`, `secret_accessed=false`, `cost_actions_performed=false`, `stopped_before_gate=true`.

## CASE C - RECOVERY

Verdict: PASS with isolated runtime DB using current source recovery path.

- Required behavior: legacy `approval_required` runs are requeued only when effective policy is `allowed_with_step_gates`; plain `allowed`, `forbidden`, `workspace_denied`, or unproven step-gate cases are not requeued incorrectly.
- FACT: `tests/integration/test_async_task_recovery.py` passed as part of the targeted regression command.
- FACT: Final targeted regression passed with `tests/integration/test_async_task_recovery.py` included.
- FACT: Production was not restarted again to force startup recovery.
- FACT: No production DB rows were seeded or mutated for this case.
- FACT: The second operator-local attempt that would have seeded runtime-safe recovery rows was rejected before execution by the approvals reviewer.
- FACT: The post-approval retry was also rejected before execution by the approvals reviewer.
- FACT: Runtime API-auth list of blocked runs returned `blocked_count=42`, but none had `last_error_code=approval_required`.
- FACT: Read-only DB query `where last_error_code='approval_required'` returned `approval_required_rows=0`.
- FACT: Core API does not expose an endpoint to seed or mark a legacy `status=blocked,last_error_code=approval_required` row for startup recovery.
- FACT: Per operator instruction, CASE C was then proven on an isolated runtime DB using the current source recovery path and no production DB/service/config change.
- FACT: Attempting to bind an isolated uvicorn port inside the sandbox failed with `PermissionError: Operation not permitted`; an escalated port run was rejected by the approvals reviewer. This was a sandbox/reviewer limitation, not a Core behavior failure.
- FACT: The isolated CASE C proof used DB `/tmp/permission-stepgate-case-c-recovery-3q5zh8ut/isolated.db` and audit `/tmp/permission-stepgate-case-c-recovery-3q5zh8ut/audit.jsonl`.
- FACT: Isolated CASE C seeded four synthetic legacy `blocked + approval_required` fixtures:
  - `stepgate`: `run_abe1d5c398be4daab5923c93aaedfc30`, `risk_level=2`, `approval_required=true`, workspace under `/mnt/f/AIOS`.
  - `plain_allowed`: `run_5d2d6a04cdbe4e2690e0875203603cf0`, `risk_level=0`, `approval_required=false`, workspace under `/mnt/f/AIOS`.
  - `forbidden`: `run_4369b631538b48baaca9cfe8ba36febd`, `risk_level=4`, `approval_required=true`, workspace under `/mnt/f/AIOS`.
  - `workspace_denied`: `run_2d2a7ceb9821473a88b5f463aa7b267a`, `risk_level=2`, `approval_required=true`, workspace `/tmp/outside-anh-duong-case-c`.
- FACT: Running the same recovery function invoked by `create_app` startup returned summary `{"requeued":0,"blocked":0,"policy_unblocked":1}`.
- FACT: `stepgate` was requeued correctly: run `status=pending`, task `status=queued`, `last_error_code=None`, `last_error_message=None`, result summary `Legacy approval block requeued after policy allowed step-level execution.`
- FACT: `plain_allowed` was not requeued: run `status=blocked`, task `status=blocked`, `last_error_code=approval_required`, `attempt=0`.
- FACT: `forbidden` was not requeued: run `status=blocked`, task `status=blocked`, `last_error_code=approval_required`, `attempt=0`.
- FACT: `workspace_denied` was not requeued: run `status=blocked`, task `status=blocked`, `last_error_code=approval_required`, `attempt=0`.

## Runtime DB / Task Observations

- FACT: Read-only DB query of recent `async_task_runs` succeeded.
- FACT: Recent observed run IDs included:
  - `run_1e96a64c647a4994b0b03956d7902904`, status `running`, last_error_code `gateway_timeout`, updated `2026-08-11 14:16:08.561995`.
  - `run_23d21167c8c144bc800bd4ff87cd69d6`, status `running`, updated `2026-08-11 14:08:49.370679`.
  - `run_36d3e73f2ee64a1e803aad142913809c`, status `running`, updated `2026-08-11 13:58:21.328915`.
  - `run_5b018...`, older safe health/ready run, status `completed`.
- FACT: These observations prove read access and ongoing task state visibility only. They do not prove the requested synthetic runtime E2E cases.

## Targeted Regression

- FACT: Command run:
  `.venv/bin/python -m pytest tests/unit/test_async_task_policy.py tests/integration/test_async_task_service.py tests/integration/test_async_task_worker.py::test_worker_executes_safe_prefix_for_approval_required_facebook_task tests/integration/test_async_task_recovery.py -q`
- FACT: Earlier result during this verification pass: `16 passed in 0.92s`.
- FACT: Final fresh result before closure: `16 passed in 0.76s`.
- FACT: Fresh result after the follow-up operator-local attempt was rejected: `16 passed in 0.90s`.
- FACT: Final fresh result after explicit operator approval still could not pass the reviewer gate: `16 passed in 0.78s`.
- FACT: Final fresh result after CASE A/B runtime E2E: `16 passed in 0.75s`.
- FACT: Final fresh result after isolated CASE C proof: `16 passed in 0.76s`.

## Logs

- FACT: `journalctl --no-pager -n 120 -u anh-duong-core.service` was used for service log evidence.
- FACT: `/home/thadc/anh-duong-core-8790.log` did not exist when checked.
- FACT: No secrets were printed in this artifact.

## Side-Effect Confirmation

- FACT: No destructive operation was executed.
- FACT: No publish/send-external action was executed.
- FACT: No secret/security-boundary action was executed.
- FACT: No cost-incurring action was executed.
- FACT: The failed synthetic DB write attempt did not create task/run IDs because it failed before commit.
- FACT: No additional production restart was performed by this verification pass.

## Final Health / Ready

- FACT: Final `/health` returned `{"status":"ok","service":"Ánh Dương Core","version":"0.1.0"}`.
- FACT: Final `/ready` returned `{"status":"ready","database":"ok"}`.
- FACT: Final `ss -ltnp` still showed `127.0.0.1:8790` owned by uvicorn PID `635533`.
- FACT: Follow-up final `/health` returned `{"status":"ok","service":"Ánh Dương Core","version":"0.1.0"}`.
- FACT: Follow-up final `/ready` returned `{"status":"ready","database":"ok"}`.
- FACT: Follow-up final `ss -ltnp` still showed `127.0.0.1:8790` owned by uvicorn PID `635533`.
- FACT: Final post-approval `/health` returned `{"status":"ok","service":"Ánh Dương Core","version":"0.1.0"}`.
- FACT: Final post-approval `/ready` returned `{"status":"ready","database":"ok"}`.
- FACT: Final post-CASE-A/B `/health` returned `{"status":"ok","service":"Ánh Dương Core","version":"0.1.0"}`.
- FACT: Final post-CASE-A/B `/ready` returned `{"status":"ready","database":"ok"}`.
- FACT: Journal showed real runtime evidence: two `POST /api/async-tasks` requests returned `202 Accepted` for CASE A and CASE B, subsequent `GET /api/async-tasks/{run_id}` requests returned `200 OK`, and final `/health` and `/ready` returned `200 OK`.
- FACT: Final post-isolated-CASE-C `/health` returned `{"status":"ok","service":"Ánh Dương Core","version":"0.1.0"}`.
- FACT: Final post-isolated-CASE-C `/ready` returned `{"status":"ready","database":"ok"}`.

## Git Status Before / After

- FACT: Before artifact creation, git status was already dirty with modified and untracked files.
- FACT: Final git status after artifact creation remained dirty with 19 modified files and 12 untracked files.
- FACT: The expected new untracked file from this verification pass is `artifacts/PERMISSION-STEP-GATE-E2E-20260811.md`.
- FACT: No source file was edited during this verification pass.
- FACT: Follow-up git status after the rejected operator-local attempt remained dirty with 19 modified files and 12 untracked files.

## FINAL VERDICT

PASS: CASE A and CASE B pass on the real restarted runtime through the authenticated Core API and worker. CASE C passes on an isolated runtime DB using the current source recovery path invoked by Core startup, with production DB/service/config untouched. The full checkpoint behavior is verified: create no longer blocks risk/approval metadata for step-gated work, safe work runs before gated stops, and legacy `approval_required` recovery only requeues `allowed_with_step_gates` while leaving plain allowed, forbidden, and workspace-denied fixtures blocked.
