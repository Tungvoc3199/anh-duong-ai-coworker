# VisualForge Telegram Image Generation Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the Telegram image vertical: one explicit image request produces exactly one verified image artifact and one Telegram media delivery, without owner approval; publishing externally remains separately gated.

**Architecture:** Keep Ánh Dương authoritative for routing, policy, idempotency, prompt/context, verification, and delivery contract. Wrap the verified native OpenClaw image-generation capability; do not build a second image engine or invoke an unverified fallback.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy/SQLite, Pydantic, pytest, Node test runner, OpenClaw native image capability, Telegram media delivery.

**Spec:** Implement capability visual_image_generate, map it to a read-only/owner-allowed image action with one-image/quota/no-paid-fallback constraints, bind approval continuations to the existing run, bind short Telegram follow-ups only to one unambiguous active intent, and deliver the verified artifact through the native Telegram message tool.

## Global Constraints

- Work only in the isolated worktree ad-visualforge-image-gen-final-1.
- Preserve existing source and runtime lanes; do not mutate stale worktrees or historical checkpoints.
- TDD: add focused regression tests first, run them red for the intended reason, then implement.
- Image generation is exactly one attempt per idempotency key; notification retries reuse the same artifact and never regenerate.
- No paid fallback, model fallback, duplicate generation, or owner approval for image creation.
- Facebook/external publishing is a distinct future action and must retain approval.
- Fail closed when approval/context binding is ambiguous.
- Production cutover is reversible and occurs only after targeted, static, full, and real Telegram evidence.

## Task 1 — Establish the Core image contract

Files: app/capabilities/models.py, app/routing/fast_router.py, app/capabilities/router.py, app/orchestration/workflow.py.

1. Add CapabilityKind.VISUAL_IMAGE_GENERATE.
2. Classify natural Vietnamese/English image requests such as “tạo ảnh”, “làm hình”, and “generate an image”, while preserving prompt-composition requests and excluding quoted prompt text from side-effect detection.
3. Map image generation to an explicit action with READ_ONLY risk, no approval, and constraints for one image, subscription quota only, no paid fallback, and delivery retry without regeneration.
4. Preserve the existing safety ordering for system, external communication, code, and file operations.
5. Add tests covering positive image intent, prompt intent, quoted/negated text, publish-after-create separation, and policy output.

## Task 2 — Add a verified native image adapter

Files: app/openclaw/image_generator.py, app/visualforge/executor.py, app/config.py, app/main.py.

1. Use the source/runtime-verified native OpenClaw HTTP invocation and response contract; when the gateway detaches the job, wait for the matching managed artifact behind the same run identity.
2. Recover an existing artifact by deterministic run/idempotency identity before attempting generation.
3. Enforce count=1, the selected permitted model/profile, quota-only behavior, safe paths, timeout recovery, and no second generation after uncertain delivery.
4. Verify PNG signature, MIME, byte size, dimensions, SHA-256, provider/model metadata, and media path before returning.
5. Compile the VisualForge prompt locally, then generate once and return structured artifact plus verification evidence.
6. Keep the existing prompt-only route unchanged and make image generation injectable for deterministic tests.

## Task 3 — Deliver media and preserve idempotency

Files: app/openclaw/notifier.py and its tests.

1. Parse structured image artifacts from result_json without trusting arbitrary text as a media path.
2. Send the verified path using the exact native Telegram message-tool media field and MIME contract.
3. Keep the current notification idempotency key stable across retries.
4. Return a concise text summary alongside media; fail closed on missing/invalid artifacts.
5. Prove that repeated notification attempts make no generation call and reuse the same artifact/path.

## Task 4 — Close Telegram approval and follow-up binding

Files: app/async_tasks/models.py, app/async_tasks/repository.py, app/async_tasks/service.py, app/api/async_tasks.py, integrations/openclaw-anh-duong-core/src/core-client.js, integrations/openclaw-anh-duong-core/src/hooks.js, and tests.

1. Add an atomic, authenticated lookup/resolution path for the newest pending approval scoped to Telegram chat and session. Resolve the exact existing approval and resume the same run; reject zero or ambiguous matches.
2. Accept natural continuation phrases such as “Duyệt nhé”, “Duyệt đi”, “Đồng ý”, and “OK duyệt” only when a scoped pending approval exists. Never create a new task for these phrases.
3. Persist/reuse the last prepared workflow binding for the same Telegram chat/session until terminal or TTL expiry.
4. For short references (“Đây”, “Ok làm đi”, “Tạo đi”, “Như cái này”, “Làm lại”), reuse only one unambiguous active image intent; otherwise fail closed and do not inherit unrelated work.
5. Preserve source message/session identity and idempotency; prove duplicate follow-ups cannot create duplicate runs or images.
6. Keep direct conversational messages and external publish approvals on their existing routes.

## Task 5 — Verification and production closure

1. Run focused Python tests, integration Node tests, formatting/type/static checks, and the serialized full suite.
2. Inspect git diff --check, source generation, and evidence artifacts; run an independent review against the value gate and four invariants.
3. Package an immutable candidate release, record the existing production symlink/PID, cut over reversibly, and verify /health and /ready.
4. Run one real Telegram request matching the owner’s image use case. Confirm one Core run, one verified PNG, one Telegram media delivery, and no approval/duplicate.
5. If any gate fails, revert the candidate symlink without deleting the previous release, preserve evidence, and keep the checkpoint open.
6. Close the checkpoint only after all gates and the final evidence review pass.

## Acceptance Evidence

- Router and workflow tests show visual_image_generate, READ_ONLY, approval_required=False, and one-image/no-paid-fallback constraints.
- Generator tests show one native call, deterministic artifact verification, recovery without regeneration, and rejection of invalid output.
- Notifier tests show a media payload with exact path/MIME and stable idempotency across retry.
- Approval continuation tests show the same approval ID and same run ID resumed.
- Follow-up tests show “Đây”/“Ok làm đi” inherit only one active image intent and never submit a second run.
- Production evidence shows a real PNG artifact and Telegram media delivery, with database run/result/notification records matching the one-request measurement.
