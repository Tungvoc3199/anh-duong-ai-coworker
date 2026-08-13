# Baseline A — OpenClaw-first Structured Bridge + Core Governance Plane

Date: 2026-08-13
Status: APPROVED BASELINE, implementation pending plan
Target branch: `design/openclaw-core-baseline-a-20260813`
Production impact: NONE during design/planning

## 1. Decision

Ánh Dương adopts **Baseline A** as the canonical architecture rule:

- **OpenClaw owns channel/runtime/execution capabilities.**
- **Ánh Dương Core owns business brain/governance capabilities.**
- **The integration plugin is a typed bridge, not a second runtime.**
- Before implementing any new capability, verify whether the exact deployed OpenClaw version already exposes that capability. If yes, integrate it instead of rebuilding it in Core.

This supersedes checkpoint-local assumptions that treated the Core request as permanently text-only.

## 2. Why the current system needs this correction

TG-1 intentionally minimized production risk by preserving the then-existing prepare-only Core contract. Its design explicitly accepted a minimal `CoreRequest` with text plus correlation/identity fields and rejected unknown fields. The OpenClaw adapter consequently flattened each ordinary Telegram turn into a text-centric request.

That was acceptable as a checkpoint-local integration tactic but incomplete as a system architecture: structured inbound facts such as attachments were not represented in the Core contract. The current adapter therefore has image-specific prompt parsing and retry reconstruction logic, while `buildCoreRequest()` still submits only text and IDs.

The current Core pipeline then routes and builds context primarily from `request.text`, so a turn containing caption `File đây nhé` plus a DOCX can lose the semantic fact that a document is attached.

## 3. Verified native OpenClaw surface for deployed compatibility target

The Ánh Dương plugin declares compatibility with OpenClaw `>=2026.7.1 <2026.8.0` and was built against `2026.7.1`.

OpenClaw `v2026.7.1` already documents inbound media primitives including:

- local inbound media path via `MediaPath`;
- provider/pseudo URL via `MediaUrl`;
- audio transcript via `Transcript`;
- structured outbound media fields;
- host/workspace file-read trust boundaries for local media.

OpenClaw `v2026.7.1` typed plugin hooks include:

- `before_model_resolve`, which receives the current prompt plus attachment metadata;
- `before_prompt_build`, for same-turn prompt/context injection;
- `before_agent_run`, for final pre-model blocking;
- `before_tool_call`, for tool policy enforcement;
- message/session lifecycle hooks.

Therefore Core must not implement Telegram file download, channel delivery, model execution or general tool execution when OpenClaw already owns those surfaces. For MIME classification, document extraction, image/audio/video understanding and other higher-level media behavior, implementation must reuse OpenClaw only after the exact deployed runtime proves that specific capability; otherwise only the proven missing gap may be added at the appropriate boundary.

Primary references:

- `openclaw/openclaw@v2026.7.1/docs/start/openclaw.md`
- `openclaw/openclaw@v2026.7.1/docs/plugins/hooks.md`

## 4. Canonical ownership boundary

### OpenClaw owns

1. Telegram/Zalo/channel transport and channel-specific quirks.
2. Inbound attachment receipt, download/staging, temp paths and provider references when exposed by the deployed runtime.
3. Native attachment/media handling capabilities actually verified in the deployed runtime.
4. Conversation session/runtime context.
5. Agent loop and model resolution/execution.
6. Provider/model transport and 9Router-facing execution path.
7. Tool execution surfaces: filesystem, shell, browser, messaging and other runtime tools.
8. Outbound text/media delivery, channel formatting, reply and streaming mechanics.
9. Native runtime progress/session/subagent mechanics where available and suitable.

### Ánh Dương Core owns

1. Canonical Persona/business identity.
2. Business policy, risk and approval decisions.
3. Durable user/project/task/workflow state.
4. Durable business memory and governed retrieval.
5. Business-intent routing and capability classification.
6. Context governance and token budgeting for Core-owned context.
7. Workflow resolution and durable async lifecycle where business durability is required.
8. Audit, provenance, idempotency and recovery policy.
9. Business-level constraints returned to the execution plane.

### Integration bridge owns

1. Typed translation between OpenClaw-native turn facts and Core request facts.
2. Correlation across OpenClaw run/session/message IDs and Core request/task/run IDs.
3. Sanitization/redaction of attachment metadata before crossing into Core.
4. Backward-compatible prompt/context injection from Core into the existing OpenClaw agent turn.
5. Feature-flagged rollout and fail-safe fallback to the existing stable text path.

The bridge must not become a media parser, Telegram client, model router, shell runner or durable business database.

## 5. Target data flow

```text
Telegram / Zalo
      ↓
OpenClaw channel ingestion
      ↓
OpenClaw native attachment/media/session normalization
      ↓
Ánh Dương Structured Bridge
  { text, source refs, attachment facts, correlation }
      ↓
Ánh Dương Core Governance Plane
  Persona → Policy → Routing → Capability
  → Memory/Project/Task → Context → Workflow/Approval
      ↓
OpenClaw agent/tool execution
      ↓
9Router / provider / model
      ↓
OpenClaw delivery
      ↓
Telegram / Zalo
```

## 6. Structured attachment contract

### 6.1 Principle

Core receives **facts/references**, not raw binary media by default.

The canonical backward-compatible Core extension is:

```text
attachments: tuple[AttachmentFact, ...] = ()
```

The integration plugin may map different OpenClaw-version-specific media fields into this stable Core field, but the Core contract remains `attachments`. No DB migration is required for the first implementation because request attachment facts are ephemeral unless a later durable-workflow requirement proves persistence necessary.

### 6.2 AttachmentFact minimum fields

```text
index                stable per-turn attachment position
kind                 image | audio | video | document | file | unknown
content_type         MIME/type when OpenClaw supplies it
filename             optional user-visible file name
local_ref            optional safe staged-local reference
provider_ref         optional provider/pseudo URL/reference
transcript           optional bounded OpenClaw-produced transcript
content_summary      optional bounded verified-runtime-produced digest/description
staged               whether the local reference is known readable by OpenClaw
source_message_id    correlation only
```

Rules:

- No binary file contents in the Core request.
- No unrestricted host path invention by Core.
- Do not persist local temp paths beyond their valid runtime lifetime.
- Do not log raw file contents or secrets.
- Bound transcript/summary length before Core context assembly.
- A local path/reference is evidence, not permission; execution remains under OpenClaw file/tool policy.
- `content_summary` is populated only when the deployed OpenClaw/runtime path actually produces one; the bridge does not create a replacement media engine just to fill the field.

## 7. Routing semantics

Routing must reason over **text + structured turn facts**, while preserving current text-only behavior when `attachments == ()`.

Examples:

```text
"File đây nhé" + DOCX attachment
→ attachment/document analysis intent, not empty/ambiguous text-only intent.

"Tóm tắt video này" + video attachment
→ direct read/analysis unless the user explicitly asks for side effects.

"Gửi file này cho X" + attachment
→ workflow/external communication because the action itself has side effects.
```

Attachment presence alone must not force workflow. Reading/analyzing supplied content is normally a non-side-effect turn; modifying/sending/deleting/publishing remains governed by existing business policy.

## 8. Context Builder behavior

Context Builder may include bounded attachment facts such as filename, kind, content type, transcript/summary and safe execution reference.

It must not:

- duplicate raw binary content;
- eagerly parse Office/PDF/media that OpenClaw already handles;
- copy unbounded transcripts into every prompt;
- convert temporary path metadata into durable memory automatically.

Core memory stores user/business knowledge only when existing memory policy says it should, not merely because an attachment arrived.

## 9. Plugin hook design

The implementation must first inspect the **effective deployed OpenClaw 2026.7.1 hook payload**, not assume current-main payloads are identical.

Preferred path if runtime evidence confirms the documented contract:

1. Capture attachment metadata at the earliest stable typed hook that exposes it, expected to be `before_model_resolve` in `v2026.7.1`.
2. Store only bounded per-run attachment facts in the plugin's existing TTL-scoped state.
3. `before_prompt_build` builds the Core request using the original semantic user prompt plus those structured facts.
4. Core returns its prepared context/policy decision.
5. `before_agent_run` remains the final Core-preparation gate.
6. `agent_end` clears per-run state.

Do not parse `[Image]`, `[Image understood: ...]` or similar text envelopes when a first-class typed media fact exists. Legacy parsing remains only as a compatibility fallback during migration and is removed only after runtime/E2E evidence proves the typed path complete.

## 10. Tool/policy boundary

Core owns business policy; OpenClaw owns actual runtime tool execution.

Where useful, Core's prepared decision may narrow tool access or require approval through documented OpenClaw tool-policy surfaces. It must not grant broader permissions than OpenClaw's host policy. Layering is fail-closed:

```text
Core business policy ALLOW
AND OpenClaw runtime/host policy ALLOW
→ tool may execute
```

A deny/block at either layer wins.

## 11. Keep / reuse / redesign / deprecate matrix

| Area | Decision | Reason |
|---|---|---|
| `app/persona` | KEEP | Core-owned brain/governance |
| `app/policy` | KEEP | Core-owned business risk/approval |
| `app/memory` | KEEP | durable business memory |
| `app/projects`, `app/tasks` | KEEP | durable business registry |
| `app/routing`, `app/capabilities` | REDESIGN INPUT | preserve logic but add structured turn facts |
| `app/context_builder` | EXTEND | render bounded attachment facts only |
| `app/orchestration/CoreRequest` | EXTEND BACKWARD-COMPATIBLY | remove text-only blind spot |
| `integrations/openclaw-anh-duong-core` | REDESIGN BRIDGE | typed OpenClaw → Core translation |
| image-envelope parsing in plugin | DEPRECATE AFTER PROOF | compatibility fallback only |
| Telegram download/client logic in Core | DO NOT BUILD | OpenClaw owns it |
| media/Office/PDF parser engine in Core | DO NOT BUILD by default | reuse only verified native/runtime capability; otherwise reassess the gap |
| provider/model transport in Core | DO NOT BUILD | OpenClaw + 9Router own it |
| `app/openclaw/executor.py` | KEEP BOUNDARY, REVIEW CONTRACT | Core may invoke OpenClaw for durable workflow execution |
| `app/openclaw/notifier.py` | KEEP BOUNDARY, REVIEW NATIVE SURFACE | delivery stays through OpenClaw |
| `PROJECT.md`, `STATE.md` | UPDATE LATER IN SAME ARCH CLOSURE | currently stale versus real system |

## 12. Zero-disruption development and rollout

Production must continue serving while this is developed.

### Gate 0 — current closure prerequisite

The already-active Codex-unattended/Git-closure checkpoint remains logically prior to runtime-affecting implementation. Design/spec work may live on this isolated branch, but no Baseline-A runtime cutover occurs until the active Git closure is clean.

### Gate 1 — read-only runtime truth

Before coding runtime integration:

- verify actual OpenClaw image/version;
- inspect effective registered plugin hooks;
- capture the real v2026.7.1 attachment hook/event shape with no user-content logging;
- compare runtime plugin package/hash/config against tracked source;
- verify Core source/runtime/Git state and existing unrelated dirty work.

### Gate 2 — isolated development

- dedicated worktree/branch;
- no edits in production working tree;
- TDD for contract/plugin/router/context changes;
- no DB migration/provider/model/token changes.

### Gate 3 — shadow observation

Feature flag records only sanitized attachment-fact shape/counters while the existing user-visible path remains authoritative. No model routing or reply behavior changes.

### Gate 4 — fixture verification

At minimum:

- text-only regression;
- image;
- PDF;
- DOCX/Office document;
- audio/voice transcript;
- video/media reference;
- multiple attachments;
- oversized/unsupported attachment;
- missing/stale staged local reference;
- retry continuation;
- workflow request carrying an attachment.

### Gate 5 — real Telegram E2E

A real Telegram-origin turn must prove correlation from inbound OpenClaw media fact → Core prepared request → agent execution → final Telegram reply. User content is not persisted in diagnostic artifacts beyond sanitized hashes/metadata unless explicitly required.

### Gate 6 — controlled cutover

- enable feature flag only after readiness/tests/E2E pass;
- preserve old text path as rollback during the first cutover window;
- no broad restart: recreate/reload only the minimum runtime component required by the actual deployment mechanism;
- verify Core `/health`, `/ready`, Gateway health and Telegram text regression after cutover.

### Gate 7 — authoritative closure

Only CLOSED when:

- runtime matches tracked config/source;
- authoritative GitHub commit contains the implemented bridge;
- text regression and attachment E2E pass;
- rollback path is documented and verified;
- no unrelated dirty work was staged or altered.

## 13. Failure behavior

The system should distinguish:

- Core unavailable/auth/contract failure;
- attachment metadata unavailable;
- local media staging pending/missing;
- unsupported attachment kind;
- verified OpenClaw extraction/understanding path failure when such a path is in use;
- model/tool execution failure.

Do not map every media issue to the generic `Ánh Dương Core hiện chưa sẵn sàng...` message. The user-facing fallback should reflect the actual bounded failure category without leaking internal paths/tokens.

Text-only turns must continue to work even if attachment-specific enrichment fails, unless the user request is impossible without the missing attachment.

## 14. Security and privacy

- No provider/token/secret changes in this project.
- No raw auth headers or token values in logs/artifacts.
- Attachment local paths are bounded runtime references, not durable identity.
- Core does not broaden OpenClaw filesystem trust.
- External sending/publishing remains governed by approval/policy.
- DB/schema migration is out of scope for the first attachment bridge.
- No destructive Git or production operations during development.

## 15. Acceptance criteria

Baseline A implementation is acceptable only when all are true:

1. Existing plain-text Telegram conversation path remains behaviorally compatible.
2. Production remains available during development.
3. DOCX/PDF/image/audio/video turns reach the agent with a usable verified-runtime content/reference path and the correct caption correlation.
4. `File đây nhé` plus a document is routed as a content-bearing request, not a text-only ambiguous request.
5. Core does not implement Telegram file download or a duplicate general media engine.
6. Attachment presence alone does not incorrectly create a side-effect workflow.
7. Unsupported/staging failures degrade cleanly and specifically.
8. No attachment binary is persisted in Core by default.
9. Exact deployed OpenClaw hook/media contract is proven before depending on it.
10. Tests cover text regression, media types, retry and workflow cases.
11. Real Telegram E2E passes.
12. Runtime + tracked config/source + authoritative Git commit are consistent at closure.

## 16. Non-goals

This project does not:

- replace OpenClaw;
- build a new Telegram client;
- build a general-purpose document/media ingestion platform inside Core;
- change 9Router/provider/model configuration;
- migrate the DB unless a later proven durability requirement needs it;
- redesign CE-2 or CACHE-2T;
- perform unrelated refactors.

## 17. Final architecture rule

For every future capability:

```text
1. Verify exact deployed OpenClaw runtime/version.
2. Check whether OpenClaw already owns/provides the capability.
3. If YES → REUSE through a typed bridge.
4. If PARTIAL → build only the missing business/governance gap.
5. If NO → decide explicitly whether it belongs to Core or the execution plane.
6. Never duplicate runtime/channel/media/tool functionality in Core by default.
7. Develop isolated; cut over only after fresh verification.
```
