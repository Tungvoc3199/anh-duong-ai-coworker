# Baseline A Structured Attachment Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backward-compatible structured attachment bridge so OpenClaw-native inbound attachment facts reach Ánh Dương Core for routing/context without rebuilding Telegram/media execution inside Core, then verify the branch before any merge to `main`.

**Architecture:** OpenClaw remains the channel/runtime/execution plane. The plugin normalizes verified runtime attachment metadata into `AttachmentFact` values and passes them through `CoreRequest.attachments`; Core uses those facts only for business routing/context/policy. The current text-only path remains unchanged when no attachments are present and remains the rollback path during initial rollout.

**Tech Stack:** Python 3.12, FastAPI/Pydantic 2, existing deterministic router/context builder, Node.js ESM plugin with `node:test`, OpenClaw compatibility `>=2026.7.1 <2026.8.0`, GitHub isolated branch/worktree, existing pytest/Ruff/Mypy/Compileall + plugin tests.

## Global Constraints

- Production must remain available during development and verification.
- Do not edit the active production working tree during implementation.
- Do not merge or push implementation into authoritative `main` before branch tests and real Telegram attachment E2E pass.
- OpenClaw owns Telegram/Zalo transport, inbound attachment receipt/staging, agent/model/tool execution and outbound delivery.
- Core owns Persona, Policy, Memory, Project/Task/Workflow, Routing, Context, Approval and Audit.
- Core contract field is exactly `attachments`.
- Core receives structured facts/references; no raw binary attachment payload.
- No DB migration in this implementation.
- No provider/model/token/9Router changes.
- No broad restart/deploy during development.
- Existing plain-text Telegram behavior must remain compatible.
- Attachment presence alone must not force a workflow.
- Legacy image-envelope parsing remains a compatibility fallback until typed-path E2E proves complete.
- Never stage/reset/clean/stash/revert unrelated production work.

---

## File structure

**Core contract / orchestration**
- Modify `app/orchestration/models.py` — define immutable `AttachmentFact`; add `CoreRequest.attachments`.
- Modify `app/orchestration/pipeline.py` — pass structured attachment facts into router/capability/context and audit only bounded metadata.
- Modify `app/orchestration/__init__.py` if exports are explicit.

**Routing / context**
- Modify `app/routing/fast_router.py` — add optional structured input facts without changing text-only behavior.
- Modify `app/context_builder/models.py` — add bounded attachment facts to `ContextBuildRequest`.
- Modify the existing context builder implementation that assembles `ContextSection`s — add one bounded attachment section only when attachments exist.
- Modify `app/context_builder/__init__.py` only if a new exported type is required.

**OpenClaw bridge**
- Create `integrations/openclaw-anh-duong-core/src/attachments.js` — version-tolerant normalization of verified OpenClaw attachment metadata to stable Core JSON.
- Modify `integrations/openclaw-anh-duong-core/src/core-client.js` — accept `attachments` in `buildCoreRequest()` and serialize it.
- Modify `integrations/openclaw-anh-duong-core/src/hooks.js` — correlate typed attachment facts with the same turn before `before_prompt_build` prepares Core.
- Modify `integrations/openclaw-anh-duong-core/index.js` — register the verified attachment-aware hook exposed by the deployed OpenClaw runtime.

**Tests**
- Create `tests/unit/test_attachment_facts.py`.
- Modify `tests/unit/test_fast_router.py`.
- Modify `tests/unit/test_context_builder.py` and `tests/unit/test_context_builder_budget.py`.
- Modify `tests/integration/test_prepared_requests.py` or the existing prepare-endpoint integration test that validates `CoreRequest` JSON.
- Create `integrations/openclaw-anh-duong-core/test/attachments.test.js`.
- Modify `integrations/openclaw-anh-duong-core/test/client.test.js`.
- Modify `integrations/openclaw-anh-duong-core/test/hooks.test.js`.

---

### Task 1: Backward-compatible Core attachment contract

**Files:**
- Modify: `app/orchestration/models.py`
- Modify if needed: `app/orchestration/__init__.py`
- Create: `tests/unit/test_attachment_facts.py`

**Interfaces:**
- Produces: `AttachmentFact` with immutable bounded fields.
- Produces: `CoreRequest.attachments: tuple[AttachmentFact, ...] = ()`.
- Existing callers that send only `text` continue to validate unchanged.

- [ ] **Step 1: Write failing model tests**

```python
from pydantic import ValidationError

from app.orchestration import AttachmentFact, CoreRequest


def test_core_request_defaults_to_no_attachments() -> None:
    request = CoreRequest(text="alo")
    assert request.attachments == ()


def test_attachment_fact_normalizes_bounded_document_metadata() -> None:
    fact = AttachmentFact(
        index=0,
        kind="document",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="test.docx",
        local_ref="/tmp/openclaw/media/test.docx",
        provider_ref="media://telegram/abc",
        staged=True,
        source_message_id="42",
    )
    assert fact.kind == "document"
    assert fact.filename == "test.docx"
    assert fact.staged is True


def test_attachment_fact_rejects_unbounded_summary() -> None:
    try:
        AttachmentFact(index=0, kind="document", content_summary="x" * 8001)
    except ValidationError:
        return
    raise AssertionError("expected validation error")
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
pytest tests/unit/test_attachment_facts.py -q
```

Expected: FAIL because `AttachmentFact` / `CoreRequest.attachments` do not exist.

- [ ] **Step 3: Add the minimal immutable model**

Implement in `app/orchestration/models.py`:

```python
AttachmentKind = Literal["image", "audio", "video", "document", "file", "unknown"]


class AttachmentFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(ge=0, le=99)
    kind: AttachmentKind
    content_type: str | None = Field(default=None, max_length=255)
    filename: str | None = Field(default=None, max_length=512)
    local_ref: str | None = Field(default=None, max_length=2048)
    provider_ref: str | None = Field(default=None, max_length=2048)
    transcript: str | None = Field(default=None, max_length=8000)
    content_summary: str | None = Field(default=None, max_length=8000)
    staged: bool = False
    source_message_id: str | None = Field(default=None, max_length=128)
```

Then extend `CoreRequest`:

```python
attachments: tuple[AttachmentFact, ...] = Field(default=(), max_length=10)
```

Do not relax `extra="forbid"`.

- [ ] **Step 4: Run model tests and relevant existing request-model tests**

```bash
pytest tests/unit/test_attachment_facts.py tests/unit -q -k 'orchestration or request or attachment'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1 on the isolated implementation branch**

```bash
git add app/orchestration/models.py app/orchestration/__init__.py tests/unit/test_attachment_facts.py
git commit -m "feat(core): add structured attachment facts"
```

---

### Task 2: Make routing and context attachment-aware without changing side-effect semantics

**Files:**
- Modify: `app/routing/fast_router.py`
- Modify: `app/orchestration/pipeline.py`
- Modify: `app/context_builder/models.py`
- Modify: existing context builder assembly module used by `create_context_builder()`
- Test: `tests/unit/test_fast_router.py`
- Test: `tests/unit/test_context_builder.py`
- Test: `tests/unit/test_context_builder_budget.py`

**Interfaces:**
- Consumes: `tuple[AttachmentFact, ...]` from Task 1.
- Produces: `FastRouter.route(request: str, *, attachments: tuple[AttachmentFact, ...] = ())`.
- Produces: `ContextBuildRequest.attachments`.
- Text-only calls keep the exact current API behavior because `attachments` defaults to `()`.

- [ ] **Step 1: Add RED routing tests**

```python
from app.orchestration.models import AttachmentFact
from app.routing import FastRoute, FastRouter


def test_document_attachment_does_not_force_workflow() -> None:
    decision = FastRouter().route(
        "File đây nhé",
        attachments=(AttachmentFact(index=0, kind="document", filename="a.docx", staged=True),),
    )
    assert decision.route is FastRoute.DIRECT


def test_send_attachment_remains_workflow() -> None:
    decision = FastRouter().route(
        "Gửi file này cho Hải",
        attachments=(AttachmentFact(index=0, kind="document", filename="a.docx", staged=True),),
    )
    assert decision.route is FastRoute.WORKFLOW
```

- [ ] **Step 2: Run routing tests and verify RED**

```bash
pytest tests/unit/test_fast_router.py -q
```

Expected: FAIL because `FastRouter.route()` does not accept `attachments`.

- [ ] **Step 3: Extend router signature with minimum behavior**

Implement:

```python
def route(
    self,
    request: str,
    *,
    attachments: tuple[AttachmentFact, ...] = (),
) -> RouteDecision:
```

Preserve all current phrase/side-effect checks first. Before the final generic direct fallback, if `attachments` is non-empty return direct with a specific rule such as:

```python
RouteDecision(
    route=FastRoute.DIRECT,
    rule_id="routing.direct.attachment_context",
    reason="The turn contains attachment context but no explicit side effect.",
)
```

Do not add `attachment -> workflow` logic.

- [ ] **Step 4: Add RED context tests**

Test that attachment metadata appears once, bounded, without binary content:

```python
assert "Attachments" in bundle.rendered_context
assert "a.docx" in bundle.rendered_context
assert "application/" in bundle.rendered_context
assert binary_marker not in bundle.rendered_context
```

Test that a very long transcript/summary is truncated or bounded by the existing context budget rather than bypassing it.

- [ ] **Step 5: Pass attachment facts through pipeline/context**

In `CoreRequestPipeline.prepare()` use:

```python
route_decision = self._fast_router.route(
    request.text,
    attachments=request.attachments,
)
```

Add `attachments=request.attachments` to `ContextBuildRequest`. Add one context section for attachments with bounded human-readable facts only. Include provenance source refs like `attachment:0`; never include raw binary content.

Audit only:

```python
"attachment_count": len(request.attachments)
```

Do not write filenames, local paths, transcripts, summaries or file contents into the audit event.

- [ ] **Step 6: Run router/context/pipeline tests**

```bash
pytest tests/unit/test_fast_router.py tests/unit/test_context_builder.py tests/unit/test_context_builder_budget.py tests/unit/test_core_request_pipeline.py -q
```

If this repository uses a differently named pipeline test file, run the existing pipeline/prepared-request unit suite identified in the branch inventory; do not create a duplicate suite solely to satisfy the command name.

Expected: PASS with all pre-existing text-only cases unchanged.

- [ ] **Step 7: Commit Task 2**

```bash
git add app/routing app/orchestration app/context_builder tests/unit
git commit -m "feat(core): route and render attachment facts"
```

---

### Task 3: OpenClaw typed attachment normalizer and Core client mapping

**Files:**
- Create: `integrations/openclaw-anh-duong-core/src/attachments.js`
- Modify: `integrations/openclaw-anh-duong-core/src/core-client.js`
- Create: `integrations/openclaw-anh-duong-core/test/attachments.test.js`
- Modify: `integrations/openclaw-anh-duong-core/test/client.test.js`

**Interfaces:**
- Produces: `normalizeAttachmentFacts(attachments, { sourceMessageId }) -> Array<CoreAttachmentFact>`.
- Extends: `buildCoreRequest({ prompt, runId, senderId, chatId, sessionKey, attachments = [] })`.
- The normalizer accepts only fields actually observed/documented for the deployed OpenClaw runtime and ignores unknown fields.

- [ ] **Step 1: Add RED normalizer tests**

```js
import assert from "node:assert/strict";
import test from "node:test";
import { normalizeAttachmentFacts } from "../src/attachments.js";

test("normalizes a document attachment without copying binary content", () => {
  const result = normalizeAttachmentFacts([
    {
      path: "/tmp/openclaw/a.docx",
      contentType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      name: "a.docx",
    },
  ], { sourceMessageId: "42" });
  assert.deepEqual(result, [{
    index: 0,
    kind: "document",
    content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    filename: "a.docx",
    local_ref: "/tmp/openclaw/a.docx",
    staged: true,
    source_message_id: "42",
  }]);
});
```

Add cases for image/audio/video, missing MIME, max 10 attachments, bounded filename/ref/transcript/summary, and unknown extra fields ignored.

- [ ] **Step 2: Run plugin normalizer tests and verify RED**

```bash
cd integrations/openclaw-anh-duong-core
node --test test/attachments.test.js
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement a pure normalizer**

`attachments.js` must:

```js
export function normalizeAttachmentFacts(values, { sourceMessageId } = {}) {
  if (!Array.isArray(values)) return [];
  return values.slice(0, 10).map((value, index) => ({
    index,
    kind: classifyKind(value),
    ...boundedOptionalFields(value, sourceMessageId),
  }));
}
```

Classification order:

```text
image/* -> image
audio/* -> audio
video/* -> video
application/pdf or Office MIME -> document
other known MIME/ref -> file
missing/unknown -> unknown
```

Never read the file, fetch the URL or invoke a model inside this module.

- [ ] **Step 4: Add Core client RED test**

```js
const request = buildCoreRequest({
  prompt: "File đây nhé",
  runId: "r1",
  attachments: [{ index: 0, kind: "document", filename: "a.docx", staged: true }],
});
assert.deepEqual(request.attachments, [
  { index: 0, kind: "document", filename: "a.docx", staged: true },
]);
```

Also assert a text-only `buildCoreRequest()` omits or sends `attachments: []` consistently with the Core default chosen by the implementation; do not change any request IDs/actor/session behavior.

- [ ] **Step 5: Extend `buildCoreRequest()` minimally**

Add `attachments = []` to the argument object and append only normalized attachment JSON. Do not alter token/auth/fetch behavior in `prepareCoreRequest()`.

- [ ] **Step 6: Run plugin client/normalizer tests**

```bash
node --test test/attachments.test.js test/client.test.js
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add integrations/openclaw-anh-duong-core/src/attachments.js integrations/openclaw-anh-duong-core/src/core-client.js integrations/openclaw-anh-duong-core/test/attachments.test.js integrations/openclaw-anh-duong-core/test/client.test.js
git commit -m "feat(openclaw): normalize attachment facts for Core"
```

---

### Task 4: Correlate typed OpenClaw attachments into the same Core-prepared turn

**Files:**
- Modify: `integrations/openclaw-anh-duong-core/src/hooks.js`
- Modify: `integrations/openclaw-anh-duong-core/index.js`
- Modify: `integrations/openclaw-anh-duong-core/test/hooks.test.js`

**Interfaces:**
- Consumes: verified deployed OpenClaw attachment-aware hook payload.
- Produces: per-turn state entry containing only sanitized `attachments` plus existing prepared state.
- `beforePromptBuild()` reads correlated attachment facts and passes them to `buildCoreRequest()`.

- [ ] **Step 1: Runtime contract gate before implementation**

From the isolated/dev execution environment, inspect the active OpenClaw `2026.7.1` plugin hook contract and one sanitized event shape. Record only field names/counts/types, never user file content or secrets.

Acceptance evidence must explicitly identify:

```text
hook name
event attachment field name
per-item path/ref field name
per-item content type field name
per-item filename field name if present
run/session correlation fields available at that hook
```

If the deployed hook differs from docs, adapt only `attachments.js`/hook mapping; keep the Core `AttachmentFact` contract stable.

- [ ] **Step 2: Add RED hook tests for same-turn correlation**

Construct a hook event with one document attachment, invoke the attachment-aware handler then `beforePromptBuild()`, and assert the POST body to Core contains that exact sanitized attachment fact.

Add a text-only case proving no attachment mutation. Add a retry-continuation case proving attachments are reused only for the same correlated turn/session and not leaked to the next unrelated message.

- [ ] **Step 3: Implement bounded per-turn attachment state**

Add a handler such as:

```js
function beforeModelResolve(event, ctx) {
  const runId = resolveTurnRunId(ctx, event?.prompt, now());
  if (!runId) return undefined;
  const attachments = normalizeAttachmentFacts(
    event?.attachments,
    { sourceMessageId: String(ctx?.messageId ?? runId) },
  );
  if (attachments.length > 0) {
    attachmentStates.set(runId, {
      attachments,
      sessionKey: ctx?.sessionKey ?? ctx?.sessionId,
      expiresAt: now() + STATE_TTL_MS,
    });
  }
  return undefined;
}
```

Use the **actual verified field names** from Step 1. The conceptual code above defines lifecycle semantics, not permission to guess runtime property names.

`beforePromptBuild()` passes the matched attachment list to `buildCoreRequest()`. `agentEnd()` clears it. TTL sweep removes abandoned entries.

- [ ] **Step 4: Register the verified hook without removing current stable hooks**

In `index.js`, register the attachment-aware hook only if supported by the deployed plugin API. Keep `before_prompt_build`, `before_agent_run`, `before_agent_reply`, `message_sent`, `agent_end` unchanged.

Do not remove `corePromptForTelegramReply()` image parsing in this task.

- [ ] **Step 5: Run complete plugin tests**

```bash
cd integrations/openclaw-anh-duong-core
npm test
```

Expected: all existing plugin tests + new attachment tests PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add integrations/openclaw-anh-duong-core
git commit -m "feat(openclaw): bridge typed attachments into Core turns"
```

---

### Task 5: API regression, failure semantics and branch verification

**Files:**
- Modify existing prepared-request integration tests under `tests/integration/`.
- Modify plugin tests only if an uncovered regression is demonstrated.
- No production configuration changes.

**Interfaces:**
- Proves: API accepts text-only and attachment-bearing requests.
- Proves: invalid attachment facts return validation failure without affecting text-only traffic.
- Proves: unsupported/missing attachment facts degrade specifically rather than making every Core turn unavailable.

- [ ] **Step 1: Add prepare-endpoint attachment integration test**

POST a request equivalent to:

```json
{
  "text": "File đây nhé",
  "channel": "telegram",
  "actor": "telegram:test",
  "attachments": [
    {
      "index": 0,
      "kind": "document",
      "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "filename": "a.docx",
      "local_ref": "/tmp/openclaw/a.docx",
      "staged": true
    }
  ]
}
```

Assert HTTP 200, direct/non-side-effect route, attachment-aware context, and no binary persistence side effect.

- [ ] **Step 2: Run targeted Python suite**

```bash
pytest tests/unit/test_attachment_facts.py tests/unit/test_fast_router.py tests/unit/test_context_builder.py tests/unit/test_context_builder_budget.py tests/integration -q
```

Expected: PASS.

- [ ] **Step 3: Run full Core quality gates**

```bash
pytest -q
ruff check app tests
mypy app
PYTHONPYCACHEPREFIX=/tmp/anh-duong-pycache python -m compileall -q app tests
```

Expected: all PASS.

- [ ] **Step 4: Run complete OpenClaw plugin regression**

```bash
cd integrations/openclaw-anh-duong-core
npm test
```

Expected: PASS.

- [ ] **Step 5: Review exact branch diff**

```bash
git diff --check main...HEAD
git diff --stat main...HEAD
git diff main...HEAD -- \
  app/orchestration \
  app/routing \
  app/context_builder \
  integrations/openclaw-anh-duong-core \
  tests
```

Reject any DB migration, provider/model/token change, production service edit, unrelated async recovery/cache change, or binary/media parser engine added to Core.

- [ ] **Step 6: Commit any final test-only corrections**

Only if verification reveals a scoped defect; rerun the affected gate before committing.

- [ ] **Step 7: Create a pre-main test checkpoint**

Record branch SHA and the full test outputs under `/mnt/f/AIOS/anh-duong-checkpoints/BASELINE-A-ATTACHMENT-BRIDGE-<UTC>/` on the WSL host. Do not add bulky logs to source control.

---

### Task 6: Real Telegram attachment E2E before `main`

**Files:**
- No source edit unless a proven scoped defect is found.
- Runtime change is feature-flagged/minimal and must use a dev/shadow plugin path first where supported.

**Interfaces:**
- Proves end-to-end: Telegram attachment → OpenClaw attachment fact → bridge → Core prepared request → OpenClaw agent → Telegram reply.

- [ ] **Step 1: Verify production remains healthy before E2E**

Read-only:

```bash
curl -fsS http://127.0.0.1:8790/health
curl -fsS http://127.0.0.1:8790/ready
```

Gateway/OpenClaw health must also remain healthy through its existing runtime health command.

- [ ] **Step 2: Run the minimum safe branch/dev runtime activation**

Use the existing OpenClaw managed plugin installation mechanism or isolated dev runtime already established by project runbooks. Do not rebuild/upgrade OpenClaw and do not alter 9Router/model/provider/token settings.

- [ ] **Step 3: Test text regression first**

Send a normal Telegram text such as `alo`. It must still produce the normal conversational path without attachment-specific failure.

- [ ] **Step 4: Test the original DOCX failure case**

Send one `.docx` with caption:

```text
File đây nhé
```

Acceptance:

```text
OpenClaw sees one inbound attachment
bridge emits one AttachmentFact(kind=document)
Core prepare returns 200
route is not forced to workflow solely by attachment presence
agent receives usable document reference/content path
Telegram receives a meaningful response instead of "blocked by anh-duong-core"
```

- [ ] **Step 5: Test representative media cases**

At minimum one image, one PDF, one audio/voice and one video. For any type where OpenClaw `2026.7.1` does not provide a directly usable native path, record the exact proven gap rather than adding an unplanned Core media engine.

- [ ] **Step 6: Verify no cross-turn attachment leakage**

After an attachment turn, send a new plain-text message. The next Core request must have zero attachments unless the new Telegram turn itself contains one.

- [ ] **Step 7: Final pre-main decision**

Only when all required branch tests and the real DOCX E2E pass, prepare the branch for review/merge. `main` remains unchanged until explicit final integration approval and authoritative Git/runtime closure.

---

## Self-review result

- Spec coverage: contract, routing, context, bridge, verified-runtime hook gate, compatibility fallback, tests, privacy, zero-disruption rollout and real Telegram E2E are all mapped to tasks.
- Placeholder scan: no implementation placeholder is allowed; runtime-specific field names are intentionally gated by an explicit read-only contract-verification step rather than guessed.
- Type consistency: stable cross-boundary contract is `CoreRequest.attachments: tuple[AttachmentFact, ...]`; JS bridge serializes the same field name `attachments`.
- Scope: no DB migration, no provider/model/token work, no CE-2/CACHE work, no production merge/deploy in this plan.
