# AD-VISUAL-INTERACTION-CONTRACT-1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. No commits are allowed in this run; stop at the owner gate.

**Goal:** Make every visual turn use one immutable semantic contract so media selects only evidence/reference, never intent, while read-only visual questions cannot trigger image generation/edit/delivery.

**Architecture:** Build `VisualInteractionContract` once in Core before routing. `FastRouter`, `CapabilityRouter`, workflow preparation, and OpenClaw consume the same contract; OpenClaw resolves trusted media provenance but never rewrites the user's instruction into a generation command. Preserve the production runtime overlay exactly, then replace legacy sticky visual intent inference with contract-driven behavior.

**Tech Stack:** Python 3.12, Pydantic, pytest, Ruff, Mypy, Node.js ESM, `node:test`, OpenClaw plugin API.

**Spec:** `docs/superpowers/specs/2026-09-13-ad-visual-interaction-contract-1-design.md`

## Global Constraints

- Isolated worktree: `/home/thadc/AIOS/worktrees/ad-visual-interaction-contract-1`, branch `ad-visual-interaction-contract-1`, base `7017af4a9b3b6027e3c419d44786bf0425902333`.
- Preserve protected production overlay: `web_read`, recent referent plumbing, provisional prepare state, duplicate-prepare claim/reuse, owner provenance.
- Do not reset/stash/revert unrelated work.
- Do not commit, merge, push, deploy, restart, change provider/model, or touch 9Router before owner approval.
- `raw_instruction` remains the Core-received user instruction; vision/recent context cannot replace it.
- Image presence/reply/recent artifact never selects GENERATE/EDIT by itself.
- Read-only visual operations must cause zero image generation/edit workflow submission and zero `sendPhoto`.
### Task 1: Reconcile protected runtime baseline

**Files:**
- Modify: `integrations/openclaw-anh-duong-core/src/core-client.js`
- Modify: `integrations/openclaw-anh-duong-core/src/hooks.js`
- Test: `integrations/openclaw-anh-duong-core/test/hooks.test.js`
- Test: `integrations/openclaw-anh-duong-core/test/core-client.test.js`

**Interfaces:** Preserve runtime SHA content as the starting implementation baseline; no visual-contract behavior is introduced in this task.

- [ ] Copy the current production-runtime `core-client.js` and `hooks.js` from `/home/thadc/.local/state/anh-duong-golden-v1-cutover/golden/openclaw-fresh-v1/extensions/anh-duong-core/src/` into the isolated worktree.
- [ ] Verify copied hashes equal runtime hashes and `index.js` remains unchanged.
- [ ] Add/confirm focused regressions for `web_read`, `recent_referent`, provisional prepare claim/reuse, duplicate prepare reuse, and owner provenance.
- [ ] Run `node --test integrations/openclaw-anh-duong-core/test/*.test.js`; require zero failures before visual changes.

### Task 2: Define the neutral visual semantic contract — RED then GREEN

**Files:**
- Create: `app/visual_interaction.py`
- Create: `tests/unit/test_visual_interaction_contract.py`
- Create: `tests/security/test_visual_interaction_determinism.py`

**Interfaces:**
- Produce `VisualOperation`, `VisualImageRole`, `VisualImageSource`, `VisualOutput`, `VisualConstraint`, `VisualSideEffect`, `VisualInteractionContract`.
- Produce `build_visual_interaction_contract(raw_instruction: str, *, image_source: VisualImageSource = VisualImageSource.NONE, reference_image: str | None = None) -> VisualInteractionContract | None`.

- [ ] Write golden tests for ANALYZE/EXTRACT/VERIFY/COMPARE/GENERATE/EDIT/TRANSFORM/ANNOTATE, hard negation, missing/ambiguous target clarification, style-reference generation, and `đúng != dùng`.
- [ ] Run focused tests and verify RED because `app.visual_interaction` does not exist.
- [ ] Implement the enums, frozen model, diacritic-aware literal matcher, negation-before-positive classification, role/output/constraint/clarification derivation.
- [ ] Run focused tests to GREEN plus determinism/purity checks.
### Task 3: Make Core request/pipeline/router contract-aware — RED then GREEN

**Files:**
- Modify: `app/orchestration/models.py`
- Modify: `app/orchestration/pipeline.py`
- Modify: `app/routing/fast_router.py`
- Modify: `app/capabilities/models.py`
- Modify: `app/capabilities/router.py`
- Modify: `app/capabilities/__init__.py`
- Test: `tests/unit/test_fast_router.py`
- Test: `tests/unit/test_capability_router.py`
- Test: `tests/unit/test_core_request_pipeline.py`
- Test: `tests/security/test_capability_router_determinism.py`

**Interfaces:**
- `CoreRequest` gains `image_source: VisualImageSource = NONE`; source/reference pairing is validated.
- `PreparedRequest` gains `visual_interaction: VisualInteractionContract | None`.
- `FastRouter.route(text: str, visual_interaction: VisualInteractionContract | None = None) -> RouteDecision`.
- `CapabilityRouter.route(route_decision, text, visual_interaction: VisualInteractionContract | None = None) -> CapabilityDecision`.
- `CapabilityKind` gains `VISUAL_ANALYSIS = "visual_analysis"`.

- [ ] Add failing router/pipeline tests proving read-only visual operations route DIRECT + `VISUAL_ANALYSIS`, executable visual operations route WORKFLOW, clarification routes DIRECT, and every request rebuilds semantics independently.
- [ ] Run focused tests and verify expected RED from missing fields/signatures/capability.
- [ ] Wire the builder once in `CoreRequestPipeline.prepare()` before both routers; keep non-visual calls backward-compatible.
- [ ] Remove independent visual-operation inference from router/capability paths when a contract is present; preserve non-visual and visual-prompt behavior.
- [ ] Run focused Core tests to GREEN.

### Task 4: Preserve workflow safety boundaries

**Files:**
- Modify: `app/orchestration/workflow.py`
- Test: `tests/unit/test_visual_semantic_routing.py`
- Test: `tests/unit/test_visual_image_execution.py`

**Interfaces:** `VISUAL_ANALYSIS` is read-only/non-executing; existing `VISUAL_IMAGE_GENERATE` remains the legacy executor capability for GENERATE/EDIT/TRANSFORM/ANNOTATE.

- [ ] Write failing tests proving ANALYZE/EXTRACT/VERIFY/COMPARE never produce a visual workflow envelope and executable operations retain current owner-policy behavior.
- [ ] Run tests to verify RED where current workflow assumptions conflict.
- [ ] Apply the minimum workflow compatibility changes; do not modify PolicyEngine authority or VisualForge provider/model behavior.
- [ ] Run focused tests to GREEN.
### Task 5: Make OpenClaw provenance-only and contract-strict — RED then GREEN

**Files:**
- Modify: `integrations/openclaw-anh-duong-core/src/core-client.js`
- Modify: `integrations/openclaw-anh-duong-core/src/prompt.js`
- Modify: `integrations/openclaw-anh-duong-core/src/hooks.js`
- Test: `integrations/openclaw-anh-duong-core/test/hooks.test.js`
- Test: `integrations/openclaw-anh-duong-core/test/core-client.test.js`
- Test: `integrations/openclaw-anh-duong-core/test/prompt.test.js`

**Interfaces:**
- Core request sends original instruction plus `image_source` and optional `reference_image` separately.
- Prepared response validator accepts/validates `visual_interaction` and `visual_analysis`.
- Prepared context renders visual semantics/evidence availability without inventing them.

- [ ] Add failing plugin tests for direct upload ANALYZE, replied-image ANALYZE, EDIT, GENERATE_REFERENCE, ambiguous media, and a GENERATE turn followed by ANALYZE; assert no `Tạo ảnh...` rewrite for analysis/edit input.
- [ ] Add failing tests that malformed visual contract values fail closed and that `visual_analysis` gets read-only policy (`SEARCH` only web search/fetch; other read-only operations no tools).
- [ ] Run focused Node tests and verify RED against current `contextualVisualImagePrompt()`/`imageRevisionPrompt()`/sticky reuse behavior.
- [ ] Change media resolution to emit source/reference metadata only; delete semantic prompt rewriting and `visual_image_follow_up` capability reuse across different turns.
- [ ] Preserve duplicate/provisional exact-request reuse, owner provenance, web-read, and recent-referent transport behavior.
- [ ] Run focused plugin tests to GREEN.

### Task 6: Golden end-to-end semantic regressions

**Files:**
- Create: `tests/integration/test_visual_interaction_golden.py`
- Modify: `integrations/openclaw-anh-duong-core/test/hooks.test.js`

**Interfaces:** Exercise Core routing/capability plus plugin request shape using the exact real-failure phrases from the spec.

- [ ] Encode all golden phrases with expected operation/source/role/output/constraints/route/capability.
- [ ] For read-only cases assert `execution_required == false`, no async visual task submission, and plugin does not select image-generation/send tools.
- [ ] For annotation/edit/generate cases assert the concrete target/reference is preserved and no unrelated side effect is inferred.
- [ ] Run focused Core + plugin golden tests until GREEN.

### Task 7: Full regression and static verification

**Files:** No new production files unless a regression demonstrates a narrowly scoped compatibility defect.

- [ ] Run focused visual suites.
- [ ] Run full Core: `PYTHONPATH=. /home/thadc/AIOS/anh-duong-core/.venv/bin/pytest -q`.
- [ ] Run full plugin: `node --test integrations/openclaw-anh-duong-core/test/*.test.js`.
- [ ] Run `/home/thadc/AIOS/anh-duong-core/.venv/bin/ruff check app tests`.
- [ ] Run `/home/thadc/AIOS/anh-duong-core/.venv/bin/mypy app`.
- [ ] Run `/home/thadc/AIOS/anh-duong-core/.venv/bin/python -m compileall -q app`.
- [ ] Run `git diff --check` and inspect `git status --short`.
- [ ] Audit diff for provider/model/9Router/service/deploy mutations; require none.
- [ ] Compare protected runtime overlay behaviors and hashes/content semantics to prove they were not dropped.

### Task 8: Owner gate

- [ ] Summarize exact diff scope, RED→GREEN evidence, full verification counts, protected-runtime reconciliation, and remaining risks.
- [ ] Confirm canonical repos and production runtime were not mutated.
- [ ] Stop at `READY_FOR_OWNER_COMMIT_DEPLOY_GATE`; do not commit/merge/push/deploy/restart without a new explicit owner instruction.
