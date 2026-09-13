# AD-VISUAL-INTERACTION-CONTRACT-1 — Architectural Design

## Outcome

Introduce one immutable semantic contract for every visual turn so media presence,
media provenance, requested operation, expected output, preservation constraints,
and side effects are independent dimensions. Image/media context may identify the
visual subject or artifact, but it never decides what operation the user requested.

This checkpoint fixes intent/routing correctness only. It does not replace the
current image provider/model, redesign VisualForge prompt compilation, add Visual
QA, change 9Router, deploy, restart, merge, or push.

## Production truth and protected baseline

The production Core truth is `anh-duong-core-owner-consent-328a4fd.service`, source
commit `328a4fd8a4ba175ce699cd5e8b626b32392b9af5`, serving on port 8792. Fresh
inventory confirmed `/health` and `/ready` PASS before this checkpoint.

The tracked implementation base is `7017af4a9b3b6027e3c419d44786bf0425902333`.
Production plugin runtime differs intentionally from that tracked source. Protected
runtime-only behavior includes `web_read`, recent referent plumbing, provisional
`before_agent_reply` prepare state, duplicate-prepare claim/reuse, and the related
read-only tool gate. Those deltas must be reconciled into the isolated worktree
before visual implementation and must survive regression unchanged.

## Contract model

Create `VisualInteractionContract` as a frozen Pydantic model with these axes. The
builder returns `None` for non-visual turns so existing non-visual routing remains
unchanged. For a visual turn, `raw_instruction` is the exact `CoreRequest.text`
value after existing input validation and is immutable for all downstream stages:


- `raw_instruction`: the Core-received user instruction. Vision enrichment, recent
  referents, reply metadata, and generated assistant context may never replace it.
- `operation`: `CONVERSE`, `ANALYZE`, `EXTRACT`, `VERIFY`, `COMPARE`, `SEARCH`,
  `DERIVE_CONTENT`, `GENERATE`, `EDIT`, `TRANSFORM`, `ANNOTATE`, `FILE_ACTION`,
  or `EXTERNAL_ACTION`.
- `image_role`: optional `EVIDENCE`, `EDIT_TARGET`, `SUBJECT_REFERENCE`,
  `STYLE_REFERENCE`, `COMPOSITION_REFERENCE`, or `DATA_SOURCE`.
- `image_source`: `CURRENT_UPLOAD`, `REPLIED_IMAGE`, `RECENT_ARTIFACT`,
  `EXPLICIT_REFERENCE`, `NONE`, or `AMBIGUOUS`.
- `output`: `TEXT`, `STRUCTURED_DATA`, `IMAGE`, `FILE`, or `EXTERNAL_EFFECT`.
- `constraints`: ordered unique `VisualConstraint` values. This checkpoint defines
  `NO_GENERATE`, `NO_EDIT`, `PRESERVE_IDENTITY`, `PRESERVE_BACKGROUND`, and
  `PRESERVE_TEXT`; later checkpoints may extend the enum without changing the axes.
- `side_effect`: `NONE`, `SAVE`, `OVERWRITE`, `DELETE`, `SEND`, or `PUBLISH`.
- `reference_image`: optional canonical managed-media URI associated with the source.
- `clarification_required`: derived immutable boolean, true when an operation needs
  a concrete visual target/evidence but the source is `NONE` or `AMBIGUOUS`.

The contract is semantic and policy-neutral. Approval/risk remains PolicyEngine
responsibility. Visual QA and prompt compilation remain separate later layers.

## Semantic classifier

Add a pure deterministic `build_visual_interaction_contract(...)` function. It
receives only the raw instruction plus explicit media provenance/reference. It does
not receive `vision_context`, assistant prose, previous capability, or previous route.

Classification preserves Vietnamese diacritics. Accentless aliases are matched only
as literal aliases in the original text; the classifier never globally folds
`đúng` and `dùng` into one token. Therefore `đúng` cannot satisfy an action signal
for `dùng`.

Negation is resolved before positive operation classification. Explicit forms such
as `không tạo`, `k tạo`, `đừng tạo`, `don't generate`, `không sửa`, `đừng sửa`,
and equivalents add hard constraints and suppress the negated operation. A positive
read-only request in the same turn remains classifiable; for example `phân tích lỗi
trong ảnh, k tạo lại ảnh` becomes `ANALYZE + NO_GENERATE`.

Operation precedence is semantic rather than media-driven: explicit external/file
action, annotation, edit/transform, new generation, extract/verify/compare/analyze,
search/derive-content, then conversation. `GENERATE` means a new artifact. `EDIT`
means localized requested changes to an existing target. `TRANSFORM` means a broad
style/form conversion of an existing target. `ANNOTATE` means marking the existing
artifact. Merely mentioning or replying to an image never selects any of them.

## Image source and role

The OpenClaw adapter resolves only media provenance. A single trusted current upload
maps to `CURRENT_UPLOAD`; a single trusted reply image maps to `REPLIED_IMAGE`.
Multiple valid candidate images map to `AMBIGUOUS` with no guessed target. Invalid
or unsafe media paths continue to fail closed under the existing security contract.

`RECENT_ARTIFACT` and `EXPLICIT_REFERENCE` are first-class contract values but are
emitted only when a concrete, trusted managed-media reference exists. Text such as
`ảnh đấy` or recent assistant discussion alone is insufficient evidence. This
prevents the bot from claiming to have inspected pixels it does not actually have.

Role is derived from operation plus source, never the inverse. Read-only inspection
uses `EVIDENCE`; extraction uses `DATA_SOURCE`; edit/transform/annotation use
`EDIT_TARGET`. Generation with a reference uses `STYLE_REFERENCE`,
`COMPOSITION_REFERENCE`, or `SUBJECT_REFERENCE` only when the instruction explicitly
states that role. A turn with no visual reference has `image_role=None`.

An ambiguous or missing target does not silently choose a recent image. The contract
keeps the requested operation but sets `clarification_required=true`; routing then
returns a direct clarification lane with zero image-generation/edit execution.

## Routing and capability boundaries

`CoreRequestPipeline.prepare()` builds the visual contract before route/capability
selection and passes the same immutable object to both routers. No router rebuilds
visual semantics from independent keyword tables.

`FastRouter.route()` accepts an optional visual contract. For an active visual turn:

- any explicit visual side effect, `FILE_ACTION`, or `EXTERNAL_ACTION` remains a
  workflow concern;
- `clarification_required=true` routes direct so the model can ask for the target;
- `GENERATE`, `EDIT`, `TRANSFORM`, and `ANNOTATE` route workflow;
- `ANALYZE`, `EXTRACT`, `VERIFY`, `COMPARE`, `SEARCH`, and `DERIVE_CONTENT` route
  direct/read-only;
- `CONVERSE` remains direct unless an independent non-visual workflow action exists.

Add `CapabilityKind.VISUAL_ANALYSIS`. `CapabilityRouter.route()` consumes the same
contract: read-only visual operations map to `visual_analysis`; executable image
operations map to the existing `visual_image_generate` executor capability; visual
prompt composition retains its existing contract. The capability is recomputed on
every request. Previous visual capability/state is never semantic input.

The current `visual_image_generate` executor name is retained for compatibility in
this checkpoint even when `operation` is EDIT/TRANSFORM/ANNOTATE. The operation
contract, not that legacy capability name, is authoritative for later compiler work.

## Core/OpenClaw request contract

`CoreRequest` gains `image_source` with default `NONE`. `reference_image` remains the
canonical managed-media locator. Model validation enforces pairing: concrete image
sources require a valid reference; `NONE` and `AMBIGUOUS` carry no reference.

`PreparedRequest` exposes `visual_interaction` when the turn is visual. OpenClaw's
strict response validator validates every enum/value and fails closed on malformed
contracts. `buildPreparedContext()` renders the operation/source/role/output,
constraints, side effect, clarification flag, and visual-evidence availability as
Core-owned context.

The plugin no longer uses `contextualVisualImagePrompt()` or `imageRevisionPrompt()`
to prepend `Tạo ảnh...`. It sends the recovered original user instruction to Core
unchanged in meaning and sends media provenance separately. Native vision prose is
auxiliary context only and cannot become `request.text` when a trusted original turn
is available.

For `visual_analysis`, OpenClaw injects a read-only tool policy. `ANALYZE`,
`EXTRACT`, `VERIFY`, `COMPARE`, and `DERIVE_CONTENT` use `no_tools`; `SEARCH` may
use only public read-only web search/fetch tools. Every `visual_analysis` turn blocks
image creation/edit, file mutation, external send, and publish tools. If Core marks
visual evidence unavailable or clarification required, the prompt explicitly
requires a clarifying response and forbids claiming inspection of unavailable pixels.

## State and exactly-once behavior

Prepared visual workflow state may still be reused for idempotent duplicate hooks of
the same request, but it may not be reused to infer a new user's operation. The
legacy `visual_image_follow_up` branch that reuses a prior generation state for vague
follow-ups is removed. A new turn always reaches Core classification unless it is a
true duplicate/provisional prepare reuse covered by the protected runtime baseline.

The protected provisional `before_agent_reply` claim/reuse mechanism remains an
exactly-once transport optimization. It may reuse the prepared result only for the
same prompt/session/actor identity; it must not change operation or attach a previous
visual capability to different text.

Recent referent data may resolve `image_source/reference_image` only when it contains
a concrete trusted artifact. It never changes `operation`, `output`, or side effect.

## Hard invariants

- `image_present != GENERATE`.
- `reply_to_image != EDIT`.
- `recent_image != REGENERATE`.
- ANALYZE/EXTRACT/VERIFY/COMPARE with no external side effect produce zero image
  generation calls, zero edit calls, zero async visual workflow submission, and zero
  `sendPhoto` delivery.
- `NO_GENERATE` and `NO_EDIT` override positive keyword collisions in the negated
  clause.
- `raw_instruction` is never replaced by vision or recent-assistant text.
- capability and operation are recomputed each user turn.
- ambiguous visual target asks for clarification and never guesses.
- absent visual evidence forbids claims that the bot saw image content.
- `đúng` and `dùng` remain semantically distinct throughout visual classification.

## Golden regression matrix

The checkpoint must encode the real failures as tests:

- `e có thấy cái ảnh nó sai cái gì k?` → ANALYZE, text output, no generation.
- `ảnh đấy e, e xem những điều a nói có đúng k` → ANALYZE when evidence is
  available; otherwise direct clarification, never generation.
- `a đang hỏi e chứ k bảo e tạo lại ảnh` → ANALYZE/CONVERSE read-only,
  `NO_GENERATE`, generation zero.
- `phân tích lỗi trong ảnh, k tạo lại ảnh` → ANALYZE + `NO_GENERATE`.
- `e phân tích lỗi sai trong ảnh a gửi đi` → ANALYZE, approval false, no workflow.
- `khoanh hai chỗ sai` with a concrete image → ANNOTATE, image output.
- `sửa hai chỗ sai đó` with a concrete image → EDIT using that target.
- `đổi váy vàng` with a concrete image → EDIT.
- `tạo một cô gái mặc váy vàng` → GENERATE with no required reference.
- `tạo ảnh mới giống phong cách ảnh này` with a concrete image → GENERATE with
  `STYLE_REFERENCE`.
- `đừng sửa gì, chỉ nhận xét` → ANALYZE + `NO_EDIT`, no image execution.
- an immediately preceding GENERATE followed by an ANALYZE question must classify
  the second turn independently as `visual_analysis`.
- `đúng` must never match the literal action alias `dùng`.

Tests cover current upload, replied image, no image, ambiguous media, and duplicate
hook execution so the semantic and exactly-once boundaries are both exercised.

## Files and boundaries

Expected implementation surface:

- create neutral `app/visual_interaction.py` for enums, immutable contract,
  deterministic classifier, and evidence/clarification derivation so routing and
  capabilities do not import each other;
- modify `app/orchestration/models.py` for request/prepared contract fields;
- modify `app/orchestration/pipeline.py` to build the contract once before routing;
- modify `app/routing/fast_router.py` so visual routing consumes the contract;
- modify `app/capabilities/models.py`, `app/capabilities/router.py`, and exports for
  `VISUAL_ANALYSIS` and contract-aware capability selection;
- modify `app/orchestration/workflow.py` only to preserve visual constraints in the
  workflow envelope; existing policy authority remains unchanged;
- modify OpenClaw `core-client.js`, `prompt.js`, and `hooks.js` for provenance-only
  media mapping, strict contract validation, read-only visual policy, and removal of
  semantic prompt rewriting/sticky visual generation reuse;
- add focused Core unit/integration regressions and OpenClaw plugin regressions.

No database migration is required. Existing async task schema, VisualForge executor,
image generator provider/model, notifier delivery implementation, and 9Router image
provider code remain unchanged in this checkpoint unless a failing regression proves
a narrowly necessary compatibility adjustment.

## Deferred checkpoints

`AD-IMAGE-VISUAL-COMPILER-1` remains responsible for semantic intent → reference and
identity lock → clean model prompt. This contract is its input, not its replacement.

`AD-IMAGE-QUALITY-GATE-1` remains responsible for independent Visual QA,
HARD_FAIL/SOFT_FAIL/UNCERTAIN/PASS classification, repair/regeneration loops, and the
rule that generation success is not sufficient for delivery. No QA bypass or fake
`PASS` state is introduced here.

## Verification and owner gate

TDD is mandatory. Golden semantic regressions are written first and must fail for the
known architectural reasons before production code changes. Implementation then
proceeds in minimal slices with targeted GREEN verification after each slice.

Before the owner gate run, at minimum:

- focused visual contract/router/pipeline tests;
- focused OpenClaw plugin visual tests, including raw-instruction and non-sticky turn
  behavior;
- protected runtime-overlay regressions for web-read and duplicate-prepare behavior;
- full Core Pytest suite;
- full plugin Node test suite;
- Ruff, Mypy, Compileall, and `git diff --check` using project-supported commands;
- static audit proving no provider/model/9Router/deploy/service mutation;
- diff audit proving unrelated canonical changes were not copied into the worktree.

The checkpoint stops at the owner commit/deploy gate. No commit, merge, push, deploy,
restart, provider/model change, or production runtime overlay is authorized by this
implementation run.
