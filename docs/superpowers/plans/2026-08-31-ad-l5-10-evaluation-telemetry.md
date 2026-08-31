# AD-L5-10 Evaluation & Telemetry Backbone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only telemetry projection over existing durable goal state and expose it through authenticated internal APIs.

**Architecture:** Add an isolated `app.evaluation` package with typed metric contracts and a projection service. The service reads existing SQLAlchemy rows and plan JSON, never writes aggregate state, and marks unsupported metrics explicitly. Add a thin internal API router and register it in `create_app`.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Pydantic 2, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-ad-l5-10-evaluation-telemetry-design.md`

## Global Constraints
- No DB schema or migration changes.
- No Telegram token, model/provider, 9Router, OpenClaw version/config, or production architecture changes.
- Do not modify protected OpenClaw integration dirty files.
- Missing telemetry must be `unsupported`/`null`, never fabricated zero.
- Never expose raw goal/prompt/result/request/evidence/approval text in telemetry.

---

### Task 1: Per-goal telemetry projection
**Files:** Create `app/evaluation/models.py`, `app/evaluation/service.py`, `app/evaluation/__init__.py`; test `tests/unit/test_evaluation_telemetry.py`.

- [ ] Write RED tests for completed, blocked, failed, approval, replan, delivery recovery, malformed/missing telemetry, and secret leakage.
- [ ] Run focused test and verify failure because `app.evaluation` does not exist.
- [ ] Implement minimal typed metric models and projection service from existing durable rows.
- [ ] Run focused test until GREEN.

### Task 2: System aggregation
**Files:** Modify `app/evaluation/service.py`; extend `tests/unit/test_evaluation_telemetry.py`.

- [ ] Add RED tests for autonomous completion, intervention rate, recovery rate, p95, capability utilization, unsupported tokens/cost/skills/regression, and idempotent/restart-safe aggregation.
- [ ] Verify RED on missing system projection.
- [ ] Implement pure system aggregation by projecting each terminal run once.
- [ ] Run focused tests until GREEN.

### Task 3: Internal API
**Files:** Create `app/api/evaluation.py`, modify `app/main.py`; test `tests/integration/test_evaluation_api.py`.

- [ ] Add RED API tests for bearer auth, goal endpoint, system endpoint, and not-found behavior.
- [ ] Verify RED (404/missing route).
- [ ] Implement read-only router using existing internal bearer guard and session factory.
- [ ] Register router in `create_app`.
- [ ] Run API tests until GREEN.

### Task 4: Gates and evidence
- [ ] Run telemetry unit+integration tests.
- [ ] Run affected async/planning/security regressions.
- [ ] Run full pytest and compare only against the three known baseline failures.
- [ ] Run Ruff on changed Python files, compileall, `git diff --check`, secret scan, and protected-file/main-worktree hash checks.
- [ ] Independent read-only review; fix Critical/Important findings with RED→GREEN tests.
- [ ] Prepare release candidate and obtain release/deploy approval if required.
- [ ] Production cutover, real Telegram/run verification, query durable telemetry, health/ready/DB/log checks.
- [ ] Write and read back `result.json`, closure markdown, and checksums.
