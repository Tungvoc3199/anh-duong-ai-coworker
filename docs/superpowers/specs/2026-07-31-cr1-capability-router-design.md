# CR-1 Capability/Skill Router v1 — Design

## Outcome

Add a deterministic domain-layer router that consumes the verified `RouteDecision`
from Fast Router FR-1 plus the original request text, and returns one immutable
`CapabilityDecision`. It classifies only; it never executes a capability and never
returns a Policy or Approval decision.

## Public contract

- `CapabilityKind`: `conversational_response`, `memory_search`, `project_read`,
  `task_read`, `core_status_read`, `planning`, `file_operation`, `code_operation`,
  `external_communication`, `system_operation`, `unknown_workflow`.
- `CapabilityDecision`: frozen Pydantic model with `capability`, `source_route`,
  `reason_code`, and immutable `matched_signals`.
- `CapabilityRouter.route(route_decision, request)`: pure and deterministic. It uses
  no LLM, network, database, filesystem, shell, clock, or randomness.

## Classification design

Valid `direct` and `memory` decisions map one-to-one to
`conversational_response` and `memory_search`. `core_read` classifies entity signals
with the deterministic specificity order Task, Project, Core. `workflow` evaluates
side-effect groups in this order: system, external communication, code, file,
planning, unknown.

The router verifies that the supplied `RouteDecision` exactly equals the current
Fast Router result for the same request. Empty input or any mismatched decision
returns `unknown_workflow`; it preserves the supplied route in `source_route` for
auditability and uses an explicit fail-closed reason code. This invalid-input path is
not considered a mapping of a valid direct/memory/core_read route.

Signals are normalized with Unicode NFKD, case folding, Vietnamese `đ` conversion,
punctuation removal, and whitespace collapse. Phrase matching uses padded token
boundaries. `matched_signals` contains stable, ordered, namespaced signal labels and
therefore never depends on set ordering.

## Safety boundaries

- System and external side effects cannot be downgraded to planning or read-only.
- Code and file actions take precedence over planning.
- Ambiguous workflows fail closed to `unknown_workflow`.
- The result has no `allow`, `deny`, `approval`, executor, or policy field.
- No API, Telegram, OpenClaw, Context Builder, schema, migration, or runtime wiring
  changes are part of CR-1.

## Files

- Create `app/capabilities/models.py`: immutable public models.
- Create `app/capabilities/router.py`: deterministic router and signal tables.
- Create `app/capabilities/__init__.py`: public exports.
- Create `tests/unit/test_capability_router.py`: contract and classification tests.
- Create `tests/security/test_capability_router_determinism.py`: purity,
  determinism, fail-closed, and precedence tests.
- Create `docs/TASK_CR1_CAPABILITY_ROUTER.md`: complete handoff document.

All planned source, test, and documentation files are new, so no existing file needs
an overwrite backup. Rollback is deletion of the CR-1 files and artifacts only.

## Verification

Use strict TDD: first create tests and observe missing-module failure, then add the
minimal implementation. Run targeted unit/security tests, full Pytest, Ruff, Mypy,
Compileall, runtime health/readiness, Alembic revision, and Async Worker checks.

