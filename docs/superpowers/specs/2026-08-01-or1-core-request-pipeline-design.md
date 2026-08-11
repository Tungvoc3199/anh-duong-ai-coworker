# OR-1 Core Request Pipeline v1 — Design

## Outcome

OR-1 adds one synchronous application-layer entry point that prepares a natural-language request for later execution without performing any action. It composes the existing Persona Loader, Fast Router, Capability Router, Project/Task Registry readers, and Context Builder, then returns an immutable `PreparedRequest`.

The pipeline does not evaluate policy, grant approval, execute a capability, create an async run, call OpenClaw, send a message, or change Project/Task state.

## Chosen architecture

`CoreRequestPipeline` receives explicit dependencies for persona loading, routing, registry reads, context building, audit writing, clock, and request-ID generation. Production wiring constructs those dependencies from an existing SQLAlchemy session and the existing append-only audit writer. Tests replace every boundary with deterministic fakes.

Alternatives rejected:

- Endpoint-owned orchestration would couple HTTP concerns to domain sequencing and make deterministic tests harder.
- Event-driven or async orchestration would exceed OR-1 and could accidentally enqueue or execute work.

## Data flow

1. Validate and whitespace-normalize `CoreRequest.text`.
2. Load the canonical Persona snapshot from `data/persona`; retain only its version and content hash as the top-level response reference.
3. Run `FastRouter.route` and pass its exact `RouteDecision` to `CapabilityRouter.route`.
4. Read optional Project and Task through their existing services. If both IDs are present, reject a Task whose `project_id` differs from the requested Project.
5. Map registry models to the existing read-only `ProjectContextSnapshot` and `TaskContextSnapshot` contracts.
6. Call the existing `ContextBuilder` once, including `memory_scope_id`; hybrid retrieval, budgeting, graceful memory degradation, and secret redaction remain CB-1 responsibilities.
7. Return `PreparedRequest`; set `execution_required=true` only for the `workflow` fast route.
8. After successful preparation, append `request.prepared` with IDs and bounded metadata only.

## Contracts

`CoreRequest` is frozen and contains `text`, optional client-supplied `request_id`, `channel` (default `internal`), `actor` (default `internal`), optional `project_id`, `task_id`, and `memory_scope_id`. Metadata is intentionally omitted because OR-1 has no demonstrated consumer for it.

`PreparedRequest` is frozen and contains the effective `request_id`, redacted `normalized_text`, a frozen Persona reference (`version`, `content_hash`), the exact router decisions, the complete secret-safe `ContextBundle`, optional IDs, `execution_required`, propagated warnings, structured provenance, and UTC `created_at`.

Generated IDs use `req_<32 lowercase hex>` in production. Injected ID/clock dependencies make all nondeterministic fields controllable in tests.

## Errors and HTTP mapping

- Blank text or structurally invalid input: FastAPI/Pydantic `422`.
- Missing Project: `ProjectContextNotFound` → `404`.
- Missing Task: `TaskContextNotFound` → `404`.
- Explicit Project/Task mismatch: `TaskProjectMismatch` → `409`.
- Missing internal API token configuration: existing fail-closed auth → `503`.
- Missing or incorrect bearer token: existing fail-closed auth → `401`.
- Context budget failure and unexpected internal failures are not converted into misleading success responses; FastAPI's normal sanitized server-error handling applies.

## Internal API

`POST /api/internal/requests/prepare` accepts `CoreRequest` and returns `PreparedRequest` with status `200`. It reuses the existing constant-time internal bearer dependency. The endpoint opens one read-only session, builds the pipeline through the registered factory, maps only known domain errors, and never commits, queues, or executes anything.

`/health` and `/ready` remain unchanged and unauthenticated.

## Security and boundaries

- The pipeline imports no OpenClaw, Telegram, 9Router, provider SDK, network, subprocess, or async-run module.
- Text exposed by `PreparedRequest` is passed through the existing `SecretRedactor`; `ContextBuilder` remains responsible for redacting the rendered context and source references.
- Audit payload excludes raw text, rendered context, memory bodies, and credentials.
- Router/capability precedence is unchanged; Policy Engine remains the final authority outside this pipeline.

## Verification

TDD covers direct, memory, Project, Task, workflow, unknown, missing IDs, mismatch, blank input, determinism, immutable output, exact decision propagation, warning/budget propagation, audit minimization, no execution/queue calls, API auth, secret safety, import boundaries, and application wiring. Final verification runs targeted tests, full Pytest, Ruff, Mypy, Compileall, then read-only runtime checks required by the task.

