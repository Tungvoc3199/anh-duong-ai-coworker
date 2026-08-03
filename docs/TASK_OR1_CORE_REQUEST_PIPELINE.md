# OR-1 — Core Request Pipeline v1

## Outcome

OR-1 adds a production application-layer request preparation pipeline and a protected internal HTTP endpoint. The pipeline connects the existing Persona Loader, Fast Router, Capability Router, Project/Task Registry readers, Context Builder, and Hybrid Memory Retriever without executing a capability or creating async work.

## Architecture

```text
CoreRequest
  -> PersonaSnapshot
  -> FastRouter
  -> CapabilityRouter
  -> optional Project/Task snapshots
  -> ContextBuilder / HybridMemoryRetriever
  -> PreparedRequest
```

`CoreRequestPipeline` receives all boundaries through dependency injection. `create_core_request_pipeline` supplies production dependencies from an existing SQLAlchemy session. The FastAPI endpoint owns only bearer authentication, session lifetime, and HTTP error mapping.

No OR-1 module imports OpenClaw, Telegram, 9Router, provider SDKs, async task services, network clients, or subprocess APIs.

## Input contract

`CoreRequest` is immutable and rejects unknown fields.

| Field | Type | Behavior |
|---|---|---|
| `text` | `str` | Required, whitespace-normalized, blank rejected, max 20,000 chars |
| `request_id` | `str \| None` | Client trace ID; generated as `req_<32 hex>` when absent |
| `channel` | `str` | Defaults to `internal` |
| `actor` | `str` | Defaults to `internal` |
| `project_id` | `str \| None` | Optional Project Registry lookup |
| `task_id` | `str \| None` | Optional Task Registry lookup |
| `memory_scope_id` | `str \| None` | Forwarded unchanged to Context Builder retrieval |

Metadata is intentionally omitted because OR-1 has no demonstrated consumer requiring it.

## Output contract

`PreparedRequest` is immutable and contains:

- effective `request_id`;
- secret-redacted `normalized_text`;
- Persona `version` and SHA-256 `content_hash` reference;
- exact `RouteDecision` and `CapabilityDecision`;
- complete secret-safe `ContextBundle` including budget, warnings, and provenance;
- optional Project/Task IDs;
- `execution_required=true` only for the `workflow` fast route;
- structured registry/router/persona/context provenance;
- timezone-aware UTC `created_at`.

The pipeline writes one `request.prepared` audit event only after successful preparation. Its payload is limited to request/channel/registry IDs, route, capability, Persona version/hash, context token estimate, and warning count. Raw request text and rendered context are excluded.

## Error contract

| Condition | Domain error | HTTP status |
|---|---|---|
| Invalid or blank input | Pydantic validation | `422` |
| Project ID absent from registry | `ProjectContextNotFound` | `404` |
| Task ID absent from registry | `TaskContextNotFound` | `404` |
| Explicit Task/Project mismatch | `TaskProjectMismatch` | `409` |
| Internal token not configured | Existing bearer dependency | `503` |
| Bearer missing or incorrect | Existing bearer dependency | `401` |

Context Builder budget failures and unexpected infrastructure errors remain failures; the API does not convert them into a successful response.

## API contract

```http
POST /api/internal/requests/prepare
Authorization: Bearer <internal token>
Content-Type: application/json
```

Success returns `200` with `PreparedRequest`. The endpoint does not commit the SQLAlchemy session, transition Project/Task state, create `AsyncTaskRun`, enqueue work, call OpenClaw, or send a notification.

`GET /health` and `GET /ready` remain independent of internal bearer authentication.

## File tree

```text
app/
  api/prepared_requests.py
  orchestration/
    __init__.py
    errors.py
    models.py
    pipeline.py
    wiring.py
  main.py
tests/
  integration/test_core_request_api.py
  security/test_core_request_pipeline_security.py
  unit/test_core_request_pipeline.py
  unit/test_core_request_pipeline_behavior.py
docs/
  TASK_OR1_CORE_REQUEST_PIPELINE.md
  superpowers/plans/2026-08-01-or1-core-request-pipeline.md
  superpowers/specs/2026-08-01-or1-core-request-pipeline-design.md
```

## Test evidence

Baseline before OR-1:

- Pytest: `293 passed, 1 warning`.
- Ruff: pass.
- Mypy: pass on 59 source files.
- Compileall: exit 0.

TDD evidence:

- Contract RED: `ModuleNotFoundError: app.orchestration`.
- Contract GREEN: `5 passed`.
- Pipeline behavior RED: missing `CoreRequestPipeline` public symbol.
- Pipeline unit GREEN: `17 passed`.
- API RED: missing route/factory (`404` and absent factory).
- OR-1 targeted GREEN: `25 passed, 1 existing warning`.
- Reused-component regression: `166 passed, 1 existing warning`.

Final source verification:

- Full Pytest: `318 passed, 1 warning`.
- Ruff: `All checks passed!`.
- Mypy: `Success: no issues found in 65 source files`.
- Compileall: exit 0.

The warning is the pre-existing Starlette `TestClient`/`httpx` deprecation warning.

## Runtime verification

Read-only checks on 2026-08-01:

- `anh-duong-core.service`: `active/running`, PID 18937.
- `GET /health`: HTTP 200.
- `GET /ready`: HTTP 200.
- Alembic: `0003 (head)`.
- Effective process environment: `ANH_DUONG_ASYNC_WORKER_ENABLED=false`.
- Loaded drop-in: `/etc/systemd/system/anh-duong-core.service.d/99-checkpoint-4.2-g0-safe.conf`.
- Loaded safety EnvironmentFile: `/etc/anh-duong-core/checkpoint-4.2-g0-safe.env`.

The protected safety EnvironmentFile was not read directly because the current user lacks permission. The loaded path and effective process environment independently confirm the safety override.

## Rollback

No database migration, schema change, systemd change, deployment, restart, commit, or push occurred.

Rollback source by restoring `app/main.py` from the pre-change backup at `C:\tmp\anh-duong-or1-backup-20260801\main.py`, then removing only the OR-1-created source/tests/docs listed in the file tree. No database downgrade or systemd action is required. Verify exact paths before removal.

## Known limitations

- Per task rules, the service was not deployed or restarted. The running process passed health/readiness checks but will not expose the new endpoint until a separately authorized deployment/restart.
- Production preparation requires `ANH_DUONG_INTERNAL_API_TOKEN`; absence intentionally returns `503`.
- The production Persona path is relative to the service working directory (`data/persona`); the checked-in systemd unit sets the correct working directory.
- Audit write failure fails preparation rather than silently losing the audit record.
- OR-1 exposes one `request_id`; it does not add a separate `correlation_id` or unused metadata map.
