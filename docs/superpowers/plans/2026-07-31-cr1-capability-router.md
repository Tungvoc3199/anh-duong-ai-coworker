# CR-1 Capability/Skill Router v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a deterministic domain-layer Capability/Skill Router v1.

**Architecture:** A frozen Pydantic decision model is separated from a pure router.
The router validates the upstream FR-1 decision, normalizes request text, applies
explicit route-specific signal tables and precedence, and returns exactly one
classification without executing anything.

**Tech Stack:** Python 3.12, Pydantic 2, Pytest, Ruff, Mypy, WSL/PowerShell.

## Global Constraints

- Do not use an LLM, network, database, filesystem, shell, clock, or randomness in the router.
- Do not add PolicyDecision or ApprovalDecision to the capability contract.
- Do not modify API, Telegram, OpenClaw, 9Router, database schema, migration, systemd, or Async Worker configuration.
- Do not commit, push, or deploy.
- Keep `ANH_DUONG_ASYNC_WORKER_ENABLED=false` and Alembic revision `0003`.

---

### Task 1: Lock the public contract with failing tests

**Files:**
- Create: `tests/unit/test_capability_router.py`
- Create: `tests/security/test_capability_router_determinism.py`

**Interfaces:**
- Consumes: `FastRouter.route(request: str) -> RouteDecision`.
- Produces test expectations for `CapabilityKind`, `CapabilityDecision`, and
  `CapabilityRouter.route(route_decision: RouteDecision, request: str) -> CapabilityDecision`.

- [ ] Write table-driven unit tests for all eleven capability values, the four valid
  Fast Router routes, immutable decisions, public exports, core entity specificity,
  workflow precedence, and fail-closed empty/mismatched input.
- [ ] Write security tests that repeat each decision 100 times, inspect imports for
  forbidden I/O/model frameworks, assert the exact safe model fields, and cover
  adversarial side-effect/read-only mixtures.
- [ ] Run
  `.venv/bin/python -m pytest -q tests/unit/test_capability_router.py tests/security/test_capability_router_determinism.py`
  and verify RED fails because `app.capabilities` does not exist.

### Task 2: Implement the immutable contract and deterministic router

**Files:**
- Create: `app/capabilities/models.py`
- Create: `app/capabilities/router.py`
- Create: `app/capabilities/__init__.py`

**Interfaces:**
- `CapabilityKind(StrEnum)` contains the exact eleven contract values.
- `CapabilityDecision(BaseModel)` is frozen and contains exactly
  `capability`, `source_route`, `reason_code`, `matched_signals`.
- `CapabilityRouter.route(route_decision, request)` returns one decision.

- [ ] Add the enum and frozen model with non-empty `reason_code` and an immutable
  tuple of matched signals.
- [ ] Add pure normalization and token-boundary phrase matching helpers.
- [ ] Validate the supplied FR-1 decision by exact comparison with
  `FastRouter().route(request)`; return `unknown_workflow` for empty or mismatched
  input.
- [ ] Implement direct and memory one-to-one mappings.
- [ ] Implement core specificity precedence: Task, Project, Core.
- [ ] Implement workflow precedence: System, External, Code, File, Planning,
  Unknown; collect signals deterministically.
- [ ] Export the three public symbols from `app.capabilities`.
- [ ] Run the targeted tests and verify GREEN.

### Task 3: Verify regressions and runtime invariants

**Files:**
- Create: `docs/TASK_CR1_CAPABILITY_ROUTER.md`

**Interfaces:**
- Consumes all CR-1 source and test files.
- Produces complete verification evidence and rollback instructions.

- [ ] Run targeted tests again after refactoring.
- [ ] Run `.venv/bin/python -m pytest -q` and require zero failures.
- [ ] Run `.venv/bin/python -m ruff check .` and require zero errors.
- [ ] Run `.venv/bin/python -m mypy app` and require zero errors.
- [ ] Run `.venv/bin/python -m compileall -q app tests alembic` and require exit 0.
- [ ] Check the Core service is active and `/health` plus `/ready` return HTTP 200.
- [ ] Check current Alembic revision is `0003` and runtime Async Worker is false.
- [ ] Write the handoff document with outcome, contract, precedence, tree, complete
  created-file contents, verification, and rollback.
- [ ] Create a ZIP overlay whose single top-level directory is `anh-duong-core/`.
- [ ] Write exactly one checkpoint log at
  `/mnt/f/AIOS/anh-duong-checkpoints/checkpoint-CR1-one-shot.log`.

## Self-review

The plan covers each supplied CR-1 capability, valid-route mapping, precedence,
determinism, fail-closed input, safety boundary, test gate, runtime invariant, and
handoff artifact. Names and signatures are consistent across tasks. There are no
placeholder implementation steps.

