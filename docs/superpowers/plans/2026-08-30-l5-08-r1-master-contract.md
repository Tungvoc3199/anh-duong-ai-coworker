# AD-L5-08-R1 Master Contract Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Core execute durable plan DAGs with bounded budgets, persisted evidence, deterministic failure classification, evidence-driven replanning, and a fail-closed Outcome Judge before terminal success.

**Architecture:** Extend the existing `Plan` JSON persisted in `WorkflowRow.plan_payload` with backward-compatible execution state. Keep Task/Run leases, retry, policy, approval, OpenClaw and Governance boundaries unchanged; the worker becomes a bounded plan-node loop and only completes after Core judges all DoD criteria satisfied.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy, FastAPI runtime, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-30-l5-08-r1-master-contract-design.md`

## Global Constraints

- Preserve `Telegram → OpenClaw → Core → OpenClaw`; Core remains canonical brain.
- No DB migration unless proven impossible without one; persist through existing `WorkflowRow.plan_payload`.
- Legacy L5-07/L5-08 plan payloads must still validate safely.
- Do not change Telegram token, model/provider, 9Router, OpenClaw version/config or production architecture.
- Preserve existing Task/Run lease, idempotency, recovery, policy, approval and Governance semantics.
- Keep production untouched until focused tests, full regression and independent review pass.
- Keep the two known dirty OpenClaw integration files on production `main` byte-identical.

---

### Task 1: Durable execution state and ready-node scheduler

**Files:**
- Modify: `app/planning/models.py`
- Create: `app/planning/scheduler.py`
- Modify: `app/planning/__init__.py`
- Create: `tests/unit/test_plan_node_scheduler.py`
- Modify: `tests/unit/test_goal_planner.py`

**Interfaces:**
- Produces `PlanNodeState`, `PlanNodeExecution`, `ExecutionEvidence`, `ExecutionBudget`, and backward-compatible `Plan` fields.
- Produces `PlanNodeScheduler.ready_nodes(plan: Plan) -> tuple[PlanNode, ...]` and `state_for(plan, node_id)`.

- [ ] **Step 1: Write RED tests** for legacy payload loading, deterministic dependency gating, and completed-node exclusion.
- [ ] **Step 2: Run** `/home/thadc/AIOS/anh-duong-core/.venv/bin/python -m pytest -q tests/unit/test_plan_node_scheduler.py tests/unit/test_goal_planner.py` and verify failure because runtime-state types/scheduler do not exist.
- [ ] **Step 3: Implement minimal models and scheduler.** Missing execution entries are interpreted as `pending`; scheduler returns pending nodes in original plan order only when all dependencies are completed.
- [ ] **Step 4: Re-run the same tests** and require PASS.
- [ ] **Step 5: Commit** `feat(l5-08-r1): add durable plan execution state`.

### Task 2: Criterion evidence and deterministic Outcome Judge

**Files:**
- Modify: `app/openclaw/models.py`
- Create: `app/planning/outcome.py`
- Modify: `app/planning/__init__.py`
- Create: `tests/unit/test_outcome_judge.py`
- Modify: `tests/unit/test_openclaw_executor.py`

**Interfaces:**
- Produces `CriterionVerification(criterion, status, evidence_refs, explanation)` and optional `criterion_verification` on `OpenClawExecutionResult`.
- Produces `OutcomeJudge.judge(plan: Plan, result: OpenClawExecutionResult) -> OutcomeJudgement`.

- [ ] **Step 1: Write RED tests** proving `completed` without criterion evidence yields `replan`, unknown evidence never certifies, and every exact DoD criterion verified with non-empty evidence yields `satisfied`.
- [ ] **Step 2: Run** `/home/thadc/AIOS/anh-duong-core/.venv/bin/python -m pytest -q tests/unit/test_outcome_judge.py tests/unit/test_openclaw_executor.py` and verify RED.
- [ ] **Step 3: Implement minimal criterion models and judge.** Match criteria by exact normalized text; missing/unknown evidence returns `replan`, explicit unmet returns `replan`, blocked/failed model result cannot become satisfied.
- [ ] **Step 4: Re-run the same tests** and require PASS.
- [ ] **Step 5: Commit** `feat(l5-08-r1): add fail-closed outcome judge`.

### Task 3: Failure classifier and evidence-driven replanning

**Files:**
- Create: `app/planning/failure.py`
- Modify: `app/planning/replanner.py`
- Modify: `app/planning/__init__.py`
- Create: `tests/unit/test_execution_failure_classifier.py`
- Modify: `tests/unit/test_plan_replanner.py`

**Interfaces:**
- Produces `ExecutionFailureClass` and `ExecutionFailureClassifier.classify(...)`.
- Produces `PlanReplanner.reconcile_after_evidence(plan, *, failure_class, evidence, execution_started) -> ReplanDecision`.

- [ ] **Step 1: Write RED tests** for retryable transport, uncertain side effect, policy/governance, missing DoD evidence and recoverable unmet DoD; only the last two may request semantic replan.
- [ ] **Step 2: Write RED replanner tests** proving one evidence replan increments revision, preserves prior evidence/completed-node states, adds a corrective request constraint, and respects `max_replans`.
- [ ] **Step 3: Run** `/home/thadc/AIOS/anh-duong-core/.venv/bin/python -m pytest -q tests/unit/test_execution_failure_classifier.py tests/unit/test_plan_replanner.py` and verify RED.
- [ ] **Step 4: Implement the closed classifier and minimal evidence replan path.** Unknown, policy, governance and uncertain-side-effect classes fail closed.
- [ ] **Step 5: Re-run the same tests** and require PASS, then commit `feat(l5-08-r1): add evidence-driven replanning`.

### Task 4: OpenClaw node/DoD execution context

**Files:**
- Modify: `app/openclaw/models.py`
- Modify: `app/openclaw/executor.py`
- Modify: `tests/unit/test_openclaw_executor.py`

**Interfaces:**
- Extends `OpenClawExecutionRequest` with optional `plan_node_id`, `plan_node_title`, `capability_requirements`, `dod_criteria`, `verification_requirements`, `prior_evidence`, and `remaining_budget`.
- Existing request construction remains valid because every new field has a safe default.

- [ ] **Step 1: Write RED tests** proving orchestration context survives gateway serialization and executor instructions require criterion-level verification when DoD is supplied.
- [ ] **Step 2: Run** `/home/thadc/AIOS/anh-duong-core/.venv/bin/python -m pytest -q tests/unit/test_openclaw_executor.py` and verify RED.
- [ ] **Step 3: Implement optional request fields and instruction text** without provider-specific logic; keep old response normalization accepted.
- [ ] **Step 4: Re-run executor tests** and require PASS.
- [ ] **Step 5: Commit** `feat(l5-08-r1): carry plan evidence across OpenClaw boundary`.

### Task 5: Bounded worker plan-node loop and crash-safe persistence

**Files:**
- Modify: `app/async_tasks/worker.py`
- Modify: `app/planning/repository.py`
- Modify: `tests/integration/test_async_task_worker.py`
- Create: `tests/integration/test_plan_orchestration_worker.py`

**Interfaces:**
- Worker consumes `PlanNodeScheduler`, `OutcomeJudge`, `ExecutionFailureClassifier`, and `PlanReplanner`.
- `PlanRepository.save()` persists node states, evidence, budget counters and judgement in the existing JSON atomically.

- [ ] **Step 1: Write RED integration tests** for a two-action DAG, no replay of a completed node after worker restart, exhausted action budget, and model `completed` without DoD evidence failing closed.
- [ ] **Step 2: Add RED success test** where both action nodes produce criterion evidence and the verification gate completes the Run/Task only after `OutcomeJudgement.satisfied`.
- [ ] **Step 3: Run** `/home/thadc/AIOS/anh-duong-core/.venv/bin/python -m pytest -q tests/integration/test_plan_orchestration_worker.py tests/integration/test_async_task_worker.py` and verify RED for the new orchestration behavior.
- [ ] **Step 4: Implement the minimal bounded loop.** Before each action check budget; persist `running` state, execute one node, persist evidence/state, then recompute ready nodes. Verification nodes call `OutcomeJudge`; no direct `result.outcome == completed` terminal transition for planned runs.
- [ ] **Step 5: Preserve compatibility:** runs with no persisted plan continue through the existing single-execution path; approval/governed behaviors stay on their current policy boundaries until their plan node is legitimately ready.
- [ ] **Step 6: Re-run integration tests** and require PASS, then commit `feat(l5-08-r1): execute durable plan nodes with outcome judgement`.

### Task 6: Core-native evidence, budgets and regression closure

**Files:**
- Modify: `app/async_tasks/worker.py`
- Modify: `tests/integration/test_async_task_worker.py`
- Modify: `tests/unit/test_goal_planner.py`
- Modify: `tests/unit/test_plan_replanner.py`
- Modify: `tests/unit/test_openclaw_executor.py`

**Interfaces:**
- Core `/health` + `/ready` path emits criterion verification compatible with `OutcomeJudge`.
- Budget counters are durable and bounded by `ExecutionBudget` plus existing `RiskBudget.max_retries/max_replans`.

- [ ] **Step 1: Write RED regression** proving Core-native health/ready reaches satisfied judgement using the same DoD rule and no OpenClaw call.
- [ ] **Step 2: Write RED budget regressions** for action and elapsed-time exhaustion; exhausted budget yields precise blocked/failed result, never success.
- [ ] **Step 3: Implement only the missing native evidence/budget glue** and re-run focused suites.
- [ ] **Step 4: Run focused gate:** planner, scheduler, outcome, failure, replanner, executor and worker suites together.
- [ ] **Step 5: Commit** `test(l5-08-r1): close orchestration compatibility and budget gates`.

### Task 7: Full verification, review and release candidate

**Files:**
- No new production files unless a failing verification exposes a scoped defect.
- Evidence: `/mnt/f/AIOS/anh-duong-checkpoints/AD-L5-08-R1-MASTER-CONTRACT/`

**Interfaces:**
- Candidate must be clean, reviewable and fast-forwardable from current `main` lineage without touching protected production dirty files.

- [ ] **Step 1: Run full Python regression** from the isolated worktree using `/home/thadc/AIOS/anh-duong-core/.venv/bin/python -m pytest -q` and classify only reproducible pre-existing baseline failures as baseline.
- [ ] **Step 2: Run static gates:** Ruff on changed Python files, `python -m compileall -q app tests`, `git diff --check`, and a sanitized secret-pattern scan of the candidate diff.
- [ ] **Step 3: Verify scope/invariants:** no DB migration, provider/model/9Router/OpenClaw-config delta; compare protected dirty-file hashes on production `main` against their known hashes.
- [ ] **Step 4: Run independent read-only review** against the exact candidate commit; any actionable finding returns to RED→GREEN before another review.
- [ ] **Step 5: Create release-candidate evidence** with exact commit, tests, review verdict, rollback basis and production preflight; do not cut over on review failure.

### Task 8: Controlled production acceptance and return to L5-09

**Files:**
- Evidence only under `/mnt/f/AIOS/anh-duong-checkpoints/AD-L5-08-R1-MASTER-CONTRACT/` unless a production-only defect is proven.

- [ ] **Step 1: At the release gate, verify current `main`, runtime release, Core/OpenClaw health, DB quick_check, config hashes and rollback release before mutation.**
- [ ] **Step 2: Fast-forward `main` and build an immutable Core release only after the candidate remains PASS; preserve rollback.**
- [ ] **Step 3: Cut over/restart only as required, then verify service CWD/release identity, `/health=200`, `/ready=200`, DB quick_check and clean logs.**
- [ ] **Step 4: Run real Telegram production E2E** proving a planned workflow can complete only through `OutcomeJudgement.satisfied`, while an intentionally incomplete DoD response fails closed.
- [ ] **Step 5: Write `result.json` and closure report** only if production E2E, regression, review and runtime integrity all PASS.
- [ ] **Step 6: Resume `AD-L5-09` certification** from its existing isolated worktree; do not mix its real-job certification evidence into the R1 repair closure.

## Exact implementation sketches

### Task 1 model/scheduler shape

```python
class PlanNodeState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"

class PlanNodeExecution(BaseModel):
    model_config = ConfigDict(frozen=True)
    node_id: str
    state: PlanNodeState = PlanNodeState.PENDING
    attempts: int = Field(default=0, ge=0)
    evidence_ids: tuple[str, ...] = ()
    last_failure_class: str | None = None
```

`PlanNodeScheduler.ready_nodes()` builds `{node_id: state}` from `plan.node_executions`, defaults absent entries to pending, and returns plan-order nodes whose dependencies all resolve to completed.

### Task 2 criterion/judge shape

```python
class CriterionVerification(BaseModel):
    model_config = ConfigDict(frozen=True)
    criterion: str
    status: Literal["verified", "unmet", "unknown"]
    evidence_refs: tuple[str, ...] = ()
    explanation: str | None = None

class OutcomeDisposition(StrEnum):
    SATISFIED = "satisfied"
    REPLAN = "replan"
    BLOCKED = "blocked"
    FAILED = "failed"
```

`OutcomeJudge.judge(plan, result)` normalizes whitespace only, matches each `plan.definition_of_done.criteria` to one criterion verification, and requires `status == verified` plus at least one evidence ref for every criterion before returning `SATISFIED`.

### Task 3 failure/replan shape

```python
class ExecutionFailureClass(StrEnum):
    RETRYABLE_TRANSPORT = "retryable_transport"
    UNCERTAIN_SIDE_EFFECT = "uncertain_side_effect"
    POLICY_BLOCKED = "policy_blocked"
    APPROVAL_REQUIRED = "approval_required"
    GOVERNANCE_FAILURE = "governance_failure"
    DOD_EVIDENCE_MISSING = "dod_evidence_missing"
    DOD_UNMET_RECOVERABLE = "dod_unmet_recoverable"
    EXECUTION_FAILED = "execution_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNKNOWN = "unknown"
```

`reconcile_after_evidence()` may return `REVISED` only for `DOD_EVIDENCE_MISSING` or `DOD_UNMET_RECOVERABLE`, only when replan budget remains; it preserves completed node executions/evidence and resets only non-completed action nodes to pending.

### Task 4 request boundary shape

```python
class OpenClawExecutionRequest(BaseModel):
    # existing fields stay unchanged
    plan_node_id: str | None = None
    plan_node_title: str | None = None
    capability_requirements: tuple[str, ...] = ()
    dod_criteria: tuple[str, ...] = ()
    verification_requirements: tuple[str, ...] = ()
    prior_evidence: tuple[str, ...] = ()
    remaining_budget: dict[str, int] = Field(default_factory=dict)
```

When `dod_criteria` is non-empty, `_instructions()` explicitly requires a `criterion_verification` array with exact criterion text, status and evidence refs. Existing requests with empty DoD fields serialize as before except for harmless empty optional fields.

### Task 5 worker loop shape

```python
while True:
    plan = PlanRepository(session).get(run.id)
    ready = PlanNodeScheduler().ready_nodes(plan)
    if not ready:
        judgement = OutcomeJudge().judge(plan, latest_result)
        return persist_terminal_from_judgement(judgement)
    node = ready[0]
    if node.kind is PlanNodeKind.VERIFICATION_GATE:
        return evaluate_and_persist_verification(plan, node, latest_result)
    check_execution_budget(plan)
    mark_node_running_and_persist(plan, node)
    result = await executor.execute(build_node_request(plan, node))
    persist_node_result_evidence(plan, node, result)
```

The real implementation may factor helpers, but it must preserve the ordering above: durable state before side effect, durable evidence after result, judge before terminal completion.

### Task 6 budget/native evidence shape

```python
class ExecutionBudget(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_actions: int = Field(default=12, ge=1, le=128)
    max_elapsed_seconds: int = Field(default=1800, ge=1, le=86400)
    actions_used: int = Field(default=0, ge=0)
    retries_used: int = Field(default=0, ge=0)
    started_at: datetime | None = None
```

Core-native health/ready evidence must include criterion verification whose evidence refs point to durable evidence ids created from the actual HTTP probe result; it must not special-case terminal success around the judge.

## Plan self-review result

- Spec coverage: every canonical L5-08 master requirement maps to Tasks 1-8.
- Compatibility: legacy plan payloads and no-plan async runs have explicit compatibility paths.
- Persistence: all new durable state stays inside existing `WorkflowRow.plan_payload`; no schema change is planned.
- Safety: policy, approval, governance and uncertain-side-effect classes are fail-closed and cannot semantic-replan to success.
- Scope: no router/memory/Telegram UX redesign and no provider-specific orchestration.
- Type consistency: scheduler consumes `Plan.node_executions`; judge consumes `criterion_verification`; worker consumes scheduler/judge/classifier/replanner with the same names defined above.
- Release separation: implementation/review occurs in isolated worktree; production acceptance remains a later controlled gate.