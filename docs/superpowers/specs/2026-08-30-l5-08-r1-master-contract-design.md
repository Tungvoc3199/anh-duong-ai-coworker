# AD-L5-08-R1 Master Contract Repair — Design

## Status and purpose

AD-L5-08 was previously closed against a narrower local spec. The canonical L5 master plan requires more: ready-node DAG scheduling, capability/tool execution, bounded runtime budget, evidence collection, deterministic failure classification, evidence-driven replanning, and an Outcome Judge that compares evidence with Goal DoD before terminal success.

This repair restores the implementation to that canonical contract before AD-L5-09 is allowed to certify L3 autonomy. It does not lower the master plan or treat historical closure evidence as sufficient.

## Architectural invariants

- Core remains the canonical brain; OpenClaw remains the execution boundary.
- Preserve `Telegram → OpenClaw → Core → OpenClaw`; no bypass path.
- Reuse Task/Run ownership, leases, retries, recovery, idempotency, policy, approval and Governance.
- Persist orchestration state inside existing `WorkflowRow.plan_payload`; no DB migration unless implementation proves impossible without one.
- Old L5-07/L5-08 plan payloads must load with safe defaults.
- No provider/model, 9Router, Telegram token, OpenClaw version/config or production architecture changes.
- Production is untouched until implementation, regression and independent review are complete and release is separately approved.
## Durable plan runtime state

Extend the typed planning contract with backward-compatible execution metadata stored in the existing plan JSON:

- `PlanNodeState`: `pending | running | completed | blocked | failed | skipped`.
- `PlanNodeExecution`: node id, state, attempt count, last failure class, evidence ids and timestamps.
- `ExecutionEvidence`: immutable evidence id, node id, kind, summary, artifact/verification references, external run id and provenance.
- `OutcomeJudgement`: `satisfied | replan | blocked | failed`, with criterion-level results and reason code.
- `ExecutionBudget`: bounded action invocations, elapsed time, retries and replans; defaults make legacy plans valid.

`PlanRepository` remains the only persistence boundary. Saving a plan must preserve revision, node execution state, evidence and judgement atomically in `WorkflowRow.plan_payload`. Loading a legacy payload initializes missing runtime fields without rewriting the row merely by reading it.

The plan graph itself remains immutable in identity semantics: node ids are stable within a revision, completed-node evidence is never silently discarded, and a replan must increment `revision` and record `replanned_from_revision` plus the reason.
## Ready-node scheduler and execution loop

Add a small `PlanNodeScheduler` in Core. Given a validated plan plus execution state, it returns only nodes whose dependencies are completed and whose own state is pending. Tie-breaking is deterministic by plan order; it never chooses a node with an unresolved dependency.

Node kinds are handled explicitly:
- approval gate: satisfied only from the existing approval record/policy state; never sent to OpenClaw as an action;
- action: converted to one `OpenClawExecutionRequest` carrying node id/title, capability requirements, DoD, verification requirements, prior evidence and remaining budget;
- verification gate: evaluated locally by the Outcome Judge, not by trusting a model `completed` token.

The worker processes ready nodes in a bounded loop. After each action result it persists node state and evidence before moving forward. A process crash therefore resumes from durable plan state instead of replaying already completed nodes. Existing run lease/idempotency semantics remain authoritative.

Common single-action plans remain valid. Multi-node plans are exercised directly in unit/integration tests so the scheduler contract is proven independently of one particular planner decomposition strategy.
## Evidence contract and Outcome Judge

OpenClaw may report an execution result, but Core owns terminal truth. Extend the execution request/result contract so an action can return criterion-level verification evidence. Each DoD check contains the exact criterion, `verified | unmet | unknown`, and one or more evidence references or a concrete explanation.

`OutcomeJudge` is deterministic and fail-closed:
- a reported `completed` result is not enough;
- every DoD criterion must have a matching `verified` check backed by non-empty evidence;
- missing/unknown evidence yields `replan` while safe budget remains, otherwise `blocked` with a precise reason;
- explicit unmet criteria yield `replan` only when the failure classifier says the condition is recoverable and side effects are known safe;
- policy, governance, approval or uncertain-side-effect failures never become success through semantic inference;
- final Run/Task `COMPLETED` is allowed only after `OutcomeJudgement.satisfied`.

Core-native workflows such as `/health` + `/ready` produce the same typed evidence contract locally, so the judge has one success rule regardless of whether evidence came from OpenClaw or a Core-owned probe.
## Failure classification and evidence-driven replanning

Add one deterministic `ExecutionFailureClassifier` that maps transport/result/judgement state to a small closed set such as `retryable_transport`, `uncertain_side_effect`, `policy_blocked`, `approval_required`, `governance_failure`, `dod_evidence_missing`, `dod_unmet_recoverable`, `execution_failed`, `budget_exhausted`, and `unknown`.

Existing transport retry remains available only for true transport failures that are retryable and have no uncertain side effect. Semantic completion failures are not sent through blind retry.

For `dod_evidence_missing` or `dod_unmet_recoverable`, `PlanReplanner.reconcile_after_evidence()` may revise only pending/failed action semantics, preserve completed evidence, increment plan revision, and attach the failure evidence as an explicit corrective constraint. Replanning is bounded by `max_replans` and the execution budget. Truth drift after execution has begun remains fail-closed under the existing rule; evidence replanning must not weaken that protection.

If no safe replan exists, the run reaches a precise `BLOCKED` or `FAILED` terminal state and Telegram receives that blocker instead of a fabricated success.
## Runtime budget

The execution budget is checked before each action and before each automatic replan. At minimum it bounds total action invocations, retries, replans and wall-clock execution time. Exceeding any bound produces `budget_exhausted`; it never silently increases a budget or asks the owner for a routine operational choice.

Budget accounting is durable in plan payload so worker restart cannot reset consumed budget. Existing `RiskBudget.max_retries` and `max_replans` remain authoritative; new action/time limits receive conservative backward-compatible defaults.

## OpenClaw boundary

`OpenClawExecutionRequest` gains optional orchestration context: `plan_node_id`, node title, capability requirements, DoD criteria, verification requirements, prior evidence summaries and remaining budget. Old callers remain valid.

Executor instructions require structured criterion verification when DoD is supplied, but response normalization remains tolerant of older agents. Tolerance means Core may parse an old response; it does not mean the Outcome Judge may certify it without evidence.

No OpenClaw plugin/version/config change is required by design. If implementation reveals a boundary field cannot survive the existing Responses path, that becomes an explicit blocker and is not worked around by bypassing Core.
## Files and responsibilities

Expected production-code scope:
- `app/planning/models.py`: backward-compatible runtime/evidence/budget types.
- `app/planning/scheduler.py`: deterministic ready-node selection only.
- `app/planning/outcome.py`: criterion-level Outcome Judge only.
- `app/planning/failure.py`: closed deterministic failure classification only.
- `app/planning/replanner.py`: evidence-driven replan in addition to existing truth reconciliation.
- `app/planning/repository.py`: atomic persistence of extended plan payload.
- `app/openclaw/models.py`: optional node/DoD request context and typed criterion evidence.
- `app/openclaw/executor.py`: request instructions/normalization for the evidence contract.
- `app/async_tasks/worker.py`: bounded orchestration loop and terminal transition through Outcome Judge.
- `app/planning/__init__.py`: public planning interfaces.

Tests should be focused in new unit files for scheduler/outcome/failure plus the existing planner/replanner/worker/executor suites. No unrelated refactor is in scope.

## Compatibility and migration

No Alembic change is planned. Existing plan revision 1 payloads without execution metadata must validate and behave as a single-action legacy plan with empty evidence and fresh conservative budget counters. Existing non-planned async runs continue through the current compatible path.

The two known dirty OpenClaw integration files on production `main` are outside this repair and must remain byte-identical. Telegram direct/memory/core_read behavior from the follow-up guard checkpoint is a mandatory regression surface.
## Verification strategy

TDD is mandatory. Required RED→GREEN coverage:
- ready-node ordering and dependency gating on a multi-node DAG;
- crash/resume does not replay completed nodes;
- action/time/retry/replan budget exhaustion fails closed;
- completed model result without DoD evidence cannot complete Task/Run;
- all DoD criteria verified with evidence permits completion;
- recoverable missing/unmet evidence triggers exactly one bounded evidence replan and preserves prior evidence;
- uncertain-side-effect, governance and policy failures cannot auto-replan to success;
- legacy plan payloads remain readable;
- Core-native health/ready result passes the same Outcome Judge contract;
- existing truth-drift rules, scheduler priority, retry/recovery, idempotency and notification behavior remain green.

After focused tests: run relevant full Python regression, Ruff, compileall, `git diff --check`, secret scan and independent read-only review. No production cutover occurs on review failure.

## Production acceptance for AD-L5-08-R1

After separate release approval, production E2E must prove a real planned workflow reaches terminal success only through the Outcome Judge, records plan/evidence/budget state durably, and delivers Telegram final output. A deliberately incomplete verification response must fail closed rather than become completed. Core `/health` and `/ready`, DB `quick_check`, service state and recent logs must remain clean.

AD-L5-08-R1 closes only when the canonical master-plan contract is evidenced. Only then may AD-L5-09 resume its separate certification job: one nontrivial outcome request, at least two capability/tool steps, one recoverable failure or replan branch, explicit DoD verification, final Telegram delivery, and zero owner operational intervention except a legitimate predefined safety approval.

## Non-goals

- Do not implement L5-10 telemetry/learning metrics here.
- Do not redesign Fast Router, Context Builder, memory or Telegram UX.
- Do not add provider-specific orchestration to Core.
- Do not use AD-L5-09 itself as a substitute for missing AD-L5-08-R1 unit/integration evidence.
- Do not mark a historical narrow L5-08 closure as sufficient evidence for the repaired master contract.
