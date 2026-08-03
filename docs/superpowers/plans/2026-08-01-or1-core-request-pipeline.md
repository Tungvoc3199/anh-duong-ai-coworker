# OR-1 Core Request Pipeline v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-ready, side-effect-free application pipeline and protected internal API that prepare natural-language requests using the existing Core components.

**Architecture:** A synchronous `CoreRequestPipeline` owns sequencing and depends on narrow read/build interfaces. Production wiring adapts existing services; a thin FastAPI router handles authentication, session lifetime, and domain-error mapping.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, SQLAlchemy 2, Pytest, Ruff, Mypy.

## Global Constraints

- Use `datetime.UTC`; all output models are immutable.
- Do not use an LLM for routing or capability selection.
- Do not add ALLOW, DENY, APPROVAL, execution, queueing, OpenClaw, Telegram, 9Router, network, shell, migration, or schema logic.
- Reuse Persona Loader, Fast Router, Capability Router, Project/Task services, Context Builder, and Hybrid Memory Retriever.
- Preserve CB-1 graceful memory failure and secret redaction.
- Reuse existing fail-closed bearer auth; keep `/health` and `/ready` unauthenticated.
- Keep `ANH_DUONG_ASYNC_WORKER_ENABLED=false` and do not modify systemd.
- Do not commit, push, deploy, or create migrations.

---

### Task 1: Immutable request and response contracts

**Files:**
- Create: `app/orchestration/models.py`
- Create: `app/orchestration/errors.py`
- Create: `app/orchestration/__init__.py`
- Test: `tests/unit/test_core_request_pipeline.py`

**Interfaces:**
- Consumes: existing `PersonaSnapshot`, `RouteDecision`, `CapabilityDecision`, and `ContextBundle`.
- Produces: `CoreRequest`, `PersonaReference`, `RequestProvenance`, `PreparedRequest`, `ProjectContextNotFound`, `TaskContextNotFound`, and `TaskProjectMismatch`.

- [ ] **Step 1: Write failing contract tests**

  Assert blank text is rejected, whitespace is normalized, response models are frozen, UTC timestamps are required, and package exports are stable.

- [ ] **Step 2: Verify RED**

  Run `.venv/bin/python -m pytest tests/unit/test_core_request_pipeline.py -q`; expect collection failure because `app.orchestration` does not exist.

- [ ] **Step 3: Implement minimal contracts**

  Add frozen Pydantic models with bounded nonblank identifiers and a text validator using `" ".join(value.split())`. Add narrow domain error classes carrying the relevant IDs.

- [ ] **Step 4: Verify GREEN**

  Re-run the targeted unit file and confirm the contract tests pass.

### Task 2: Deterministic orchestration service

**Files:**
- Create: `app/orchestration/pipeline.py`
- Modify: `tests/unit/test_core_request_pipeline.py`

**Interfaces:**
- Consumes: injected `persona_loader()`, `FastRouter.route(text)`, `CapabilityRouter.route(decision, text)`, Project/Task readers, `ContextBuilder.build(request)`, `AuditWriter.write(event)`, `clock()`, and `id_factory()`.
- Produces: `CoreRequestPipeline.prepare(request) -> PreparedRequest`.

- [ ] **Step 1: Add RED behavior tests**

  Cover direct, memory, Project, Task, workflow, ambiguous fallback, missing Project/Task, Project/Task mismatch, exact decision retention, warning/token-budget propagation, deterministic clock/ID, secret redaction, minimal audit payload, and absence of execution/queue calls.

- [ ] **Step 2: Verify RED**

  Run `.venv/bin/python -m pytest tests/unit/test_core_request_pipeline.py -q`; expect failures for the missing pipeline.

- [ ] **Step 3: Implement minimal sequencing**

  Load persona, route, classify capability, read optional registry records, validate Project/Task consistency, map snapshots, build context once, redact top-level normalized text, construct provenance, write one bounded `request.prepared` event, and return `PreparedRequest`. Set `execution_required` from `FastRoute.WORKFLOW` only.

- [ ] **Step 4: Verify GREEN and refactor**

  Run the unit file; keep snapshot mapping in focused private helpers and rerun after cleanup.

### Task 3: Production wiring and protected API

**Files:**
- Create: `app/orchestration/wiring.py`
- Create: `app/api/prepared_requests.py`
- Modify: `app/main.py`
- Create: `tests/integration/test_core_request_api.py`
- Create: `tests/security/test_core_request_pipeline_security.py`

**Interfaces:**
- Consumes: SQLAlchemy `Session`, `AuditWriter`, `Path("data/persona")`, existing service constructors, existing `require_internal_bearer` dependency.
- Produces: `create_core_request_pipeline(...)` and `POST /api/internal/requests/prepare`.

- [ ] **Step 1: Add RED API/security tests**

  Test 200 response, Project and Task reads, 404 mappings, 409 mismatch, 422 blank input, 401 invalid/missing auth, 503 missing auth configuration, no secret in response, health/readiness independence, no async run creation, factory registration without invocation, and forbidden-import AST scan.

- [ ] **Step 2: Verify RED**

  Run `.venv/bin/python -m pytest tests/integration/test_core_request_api.py tests/security/test_core_request_pipeline_security.py -q`; expect missing module/route failures.

- [ ] **Step 3: Implement minimal wiring and endpoint**

  Compose existing repositories/services and Context Builder. Register a session-only partial factory on `application.state`, include the new router, map known domain errors, and leave all async state untouched.

- [ ] **Step 4: Verify GREEN**

  Re-run the two API/security files and the existing health/auth/lifespan regression tests.

### Task 4: Review, documentation, and delivery

**Files:**
- Create: `docs/TASK_OR1_CORE_REQUEST_PIPELINE.md`
- Create outside overlay: `/mnt/f/AIOS/anh-duong-checkpoints/checkpoint-OR1-one-shot.log`
- Create outside overlay: `/mnt/f/AIOS/anh-duong-checkpoints/anh-duong-core-OR1-overlay.zip`

**Interfaces:**
- Consumes: final source tree and fresh command outputs.
- Produces: complete handoff documentation, one checkpoint log, and an overlay ZIP rooted at `anh-duong-core/`.

- [ ] **Step 1: Self-review security and precedence**

  Inspect the diff/import graph and search for OpenClaw, Telegram, 9Router, async-run creation, queueing, policy authority, network, and subprocess references in the new boundary.

- [ ] **Step 2: Run targeted and full verification**

  Run targeted OR-1 tests, `.venv/bin/python -m pytest -q`, Ruff, Mypy app, and Compileall. Record exact exit codes and counts.

- [ ] **Step 3: Run read-only runtime verification**

  Check service activity, `/health`, `/ready`, Alembic current `0003`, effective worker environment `false`, and the loaded safety drop-in without restart or systemd modification.

- [ ] **Step 4: Write the complete handoff**

  Include Outcome, Architecture, contracts, file tree, full contents of every created/modified file, test evidence, runtime evidence, rollback, and known limitations.

- [ ] **Step 5: Build and inspect artifacts**

  Package only OR-1 overlay paths under top-level `anh-duong-core/`, verify ZIP entries, write the single checkpoint log, and confirm no source `.orig` or temporary files remain.

