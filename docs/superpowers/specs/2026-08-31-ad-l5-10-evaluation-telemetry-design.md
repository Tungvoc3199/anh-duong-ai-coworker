# AD-L5-10 Evaluation & Telemetry Backbone Design

## Goal
Provide trustworthy per-goal and system-level evaluation telemetry for learning without inventing unavailable measurements or introducing a second mutable counter store.

## Source truth
Projection reads existing durable Core state only: `tasks`, `async_task_runs`, `workflows.plan_payload`, and `approvals`. No DB migration. No OpenClaw/provider/config change. Telemetry never returns raw goal, prompt, result summary, request JSON, evidence summaries, approval reason/preview, or secrets.

## Contract
Every metric is a typed datum with `support` (`available`, `derived`, or `unsupported`), `value`, `producer`, `durable_source`, and optional `reason`. Missing producers return `unsupported` + `null`; they never silently become zero.

Per-goal fields cover terminal status; DoD verification quality; resolved human-intervention count; approval counts/states; elapsed lifecycle seconds; retry and replan counts; failure classes; route and capabilities; delivery/recovery state; token/context/output usage support; cost support; cache attribution support; and regression-indicator support.

System projection covers terminal outcome counts, autonomous completion rate, human intervention rate, autonomous recovery rate, p95 successful completion time, token per successful goal, cost per successful goal, capability utilization, skill utilization support, and quality regression rate support.

## Metric semantics
- Terminal population: `completed`, `blocked`, `failed`; cancelled runs are excluded from learning baseline rates.
- Autonomous completion: terminal run is `completed` and has zero resolved approval rows.
- Human intervention: an approval row with `resolved_at` populated. Pending approval requests count as approvals required, not human intervention performed.
- Replans: `max(plan.revision - 1, 0)` when durable plan payload exists.
- Retries: plan `execution_budget.retries_used` when present; otherwise `max(async_task_runs.attempt - 1, 0)`. These sources are not summed to avoid double counting the same recovery path.
- Recovery opportunity: retry count > 0 or replan count > 0. Autonomous recovery: opportunity ends `completed` with zero human interventions.
- Delivery recovery: notification is `sent` with `notification_attempts > 1`.
- DoD quality: verified/satisfied final Outcome Judge criteria divided by final criterion count. Missing final criteria is unsupported, not 0.
- Elapsed time: terminal task `updated_at - created_at`; successful p95 uses completed goals only. It is labeled lifecycle wall-clock, not provider execution latency.
- Route: `workflow` only when durable workflow+plan evidence exists; otherwise unsupported.
- Capability utilization: derived from unique `plan_payload.nodes[].capability_requirements` per goal.
- Actual input/output tokens, run-scoped context tokens, monetary cost, run-scoped cache attribution, skill execution utilization, and regression rate remain unsupported until a durable producer exists. Estimated Context Builder values elsewhere are not attributed to async runs and must not be repurposed.

## Failure semantics
Malformed/missing JSON does not crash the endpoint. Affected metrics become unsupported with an explicit reason. Terminal status and other independent durable fields remain available. Pure projection means repeated reads and process restarts cannot increment counters or double-count goals.

## API
Internal bearer-authenticated read-only endpoints:
- `GET /api/internal/evaluation/goals/{run_id}`
- `GET /api/internal/evaluation/system`

## Acceptance tests
1. successful autonomous goal
2. blocked goal
3. failed goal
4. approval-required goal
5. replan/recovery goal
6. notification failure and recovery
7. restart/resume does not double-count
8. aggregation is idempotent
9. missing telemetry is visibly unsupported
10. raw prompt/secret/result text cannot leak through telemetry serialization
11. internal API auth fails closed
12. baseline regression delta remains zero
