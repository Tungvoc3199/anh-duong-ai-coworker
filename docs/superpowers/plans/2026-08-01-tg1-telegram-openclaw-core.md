# TG-1 Telegram → OpenClaw → Ánh Dương Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Route every ordinary Telegram AI turn through Ánh Dương Core preparation before OpenClaw can invoke its model/runtime, with fail-closed behavior, stable correlation, unchanged native commands, and production evidence.

**Architecture:** A dependency-free native OpenClaw plugin runs inside the existing 2026.7.1 Gateway. `before_prompt_build` calls Core and injects validated prepared context; `before_agent_run` passes only a successfully prepared Telegram turn and otherwise blocks before model input; `agent_end` clears bounded per-run state. Compose passes four environment variables, while a local npm tarball is installed into OpenClaw's permission-safe managed ext4 plugin directory. No OpenClaw image build or version change is allowed.

**Tech Stack:** JavaScript ESM, Node built-in `fetch`/`AbortSignal`/`node:test`, OpenClaw 2026.7.1 public plugin hooks, FastAPI/Pydantic Core endpoint, Docker Compose, PowerShell, Pytest/Ruff/Mypy.

## Global constraints

- Preserve Telegram token, model/provider/9Router settings, Core schema/Alembic, and `ANH_DUONG_ASYNC_WORKER_ENABLED=false` byte-for-byte where applicable.
- Never log or place in artifacts the bearer token, Authorization header, raw response body, raw chat/sender/session IDs, or full prompt.
- `ANH_DUONG_CORE_ENABLED=false` is the only deliberate legacy bypass. When enabled, every eligible failure blocks the model; no CLI or direct-model fallback exists.
- Native/admin commands stay outside the agent hooks and must retain their existing fast path.
- The checked-out OpenClaw source is 2026.7.2 while runtime is 2026.7.1; do not rebuild or replace the active image.
- The Core repo is not a Git worktree and the OpenClaw worktree contains user changes. Preserve checkpointed diffs rather than creating commits.

## Task 1: Complete immutable pre-change evidence

**Files:**
- Add: `F:\AIOS\anh-duong-checkpoints\TG-1-runtime.log`
- Backup: `F:\AIOS\anh-duong-checkpoints\backups\TG-1-20260801T114348Z\openclaw\openclaw.json`

- [ ] Copy the live `openclaw.json` into the existing TG-1 backup without printing it; restrict the backup ACL because it may contain secrets.
- [ ] Record only sanitized facts in the runtime log: Core/Gateway/Telegram health, runtime image/version, Alembic `0003`, worker false, plugin inventory warning, source/runtime version mismatch, and baseline test outcomes.
- [ ] Record SHA-256 hashes for protected configuration subsets and backup files; never print secret values.
- [ ] Verify the backup exists and the live files still match their pre-change hashes.

## Task 2: Write failing plugin contract tests

**Files:**
- Create: `integrations/openclaw-anh-duong-core/package.json`
- Create: `integrations/openclaw-anh-duong-core/test/config.test.js`
- Create: `integrations/openclaw-anh-duong-core/test/client.test.js`
- Create: `integrations/openclaw-anh-duong-core/test/hooks.test.js`

- [ ] Define a dependency-free package with `"type": "module"` and `"test": "node --test"`.
- [ ] Test `readCoreConfig(env)` for disabled mode, enabled valid config, missing token/base URL, malformed URL, and finite `1..30` second timeout.
- [ ] Test `buildCoreRequest({ prompt, runId, senderId })` emits only `text`, `request_id`, `channel`, and `actor`; actor must be a SHA-256-based pseudonym and request ID must be `tg-<runId>` within 128 characters.
- [ ] Test one authenticated POST, no retry, timeout/connection/401/403/non-2xx/invalid JSON/request-ID mismatch/invalid schema failures, and direct plus workflow success.
- [ ] Assert logs and thrown error objects do not contain token, Authorization header, raw response body, sender/chat/session IDs, or prompt.
- [ ] Test hook eligibility: Telegram plus enabled enters Core; disabled and non-Telegram return `void` and do not call Core.
- [ ] Test ordering: `before_prompt_build` records fail-closed state before awaiting; success returns `prependContext`; failure leaves a blocking state; `before_agent_run` blocks absent/pending/failed state and passes only prepared state; `agent_end` cleans state.
- [ ] Test user block message exactly:

```text
Ánh Dương Core hiện chưa sẵn sàng xử lý yêu cầu này. Vui lòng thử lại sau.
```

- [ ] Run `node --test integrations/openclaw-anh-duong-core/test/*.test.js` and confirm RED because implementation modules do not exist.

## Task 3: Implement configuration, request mapping, and response validation

**Files:**
- Create: `integrations/openclaw-anh-duong-core/src/config.js`
- Create: `integrations/openclaw-anh-duong-core/src/core-client.js`
- Create: `integrations/openclaw-anh-duong-core/src/prompt.js`

- [ ] Implement these public functions without third-party dependencies:

```js
export function readCoreConfig(env = process.env) {}
export function buildCoreRequest({ prompt, runId, senderId }) {}
export async function prepareCoreRequest({ config, request, fetchImpl = fetch }) {}
export function validatePreparedRequest(value, expectedRequestId) {}
export function buildPreparedContext(prepared) {}
```

- [ ] Accept only exact booleans for enabled mode; validate base URL protocol and timeout bounds; never include token in error messages.
- [ ] Normalize a missing/oversized run ID to a bounded SHA-256 correlation while retaining the `tg-` prefix; fail closed when the current prompt is blank or exceeds Core's 20,000-character limit.
- [ ] Send `POST <baseUrl>/api/internal/requests/prepare` with `Content-Type: application/json` and bearer auth under an abort timeout. Do not retry.
- [ ] Parse JSON only after a 2xx status and validate all consumed nested fields: request ID, normalized text, route/rule/reason, capability/source route/reason code/signals, rendered context, execution flag, warnings, Persona, provenance, and timestamp.
- [ ] Require `capability_decision.source_route === route_decision.route`; require workflow iff `execution_required=true` and non-workflow iff false.
- [ ] Build a bounded explicit context block containing request ID, route, capability, execution flag, and `context.rendered_context`; do not copy the full response or secrets.
- [ ] Run config/client tests and confirm GREEN.

## Task 4: Implement the fail-closed hook gate and plugin package

**Files:**
- Create: `integrations/openclaw-anh-duong-core/src/hooks.js`
- Create: `integrations/openclaw-anh-duong-core/index.js`
- Create: `integrations/openclaw-anh-duong-core/openclaw.plugin.json`

- [ ] Implement:

```js
export function createAnhDuongCoreHooks({ env, fetchImpl, logger, now } = {}) {}
export default {
  id: "anh-duong-core",
  name: "Ánh Dương Core Gate",
  register(api) { /* three typed runtime hooks */ },
};
```

- [ ] Scope eligibility to `ctx.messageProvider === "telegram" || ctx.channel === "telegram"`; require `ctx.runId` and fail closed if it is absent for an eligible enabled turn.
- [ ] Store only `{status, requestId, failureClass, expiresAt}` plus the prepared context string for a successful active run. Sweep expired records before each hook and clean on `agent_end`.
- [ ] `before_prompt_build`: set pending state first, call Core once, set prepared or failed, emit one sanitized structured log, return `{prependContext}` only on success.
- [ ] `before_agent_run`: return `{outcome:"pass"}` only for prepared state; otherwise return `{outcome:"block", reason:"anh_duong_core_unavailable", category:"core_unavailable", message: SAFE_MESSAGE}`.
- [ ] Register both decision hooks with a timeout larger than the validated Core timeout and register `agent_end` cleanup. The plugin manifest must use strict empty config and startup activation.
- [ ] Run all plugin tests and confirm GREEN, including one-call/no-retry and pass/block assertions.

## Task 5: Prove package compatibility against runtime 2026.7.1 before activation

**Files:**
- Inspect only: `integrations/openclaw-anh-duong-core/*`

- [ ] Run `node --check` on every plugin JavaScript file.
- [ ] Mount or copy the plugin read-only into a disposable path inside the current container and use a temporary config to run cold inventory plus `plugins inspect anh-duong-core --runtime --json` without changing live config.
- [ ] Confirm runtime inspection reports exactly three hooks and no tools, commands, HTTP routes, providers, or channels.
- [ ] Run the plugin tests inside the 2026.7.1 container so the production Node runtime, ESM loader, and platform are proven.
- [ ] Append sanitized results and exact commands to `TG-1-runtime.log`.

## Task 6: Wire Compose and runtime configuration safely

**Files:**
- Modify: `F:\AIOS\openclaw\docker-compose.yml`
- Modify: `F:\AIOS\openclaw\.env`
- Modify through OpenClaw CLI: `/home/node/.openclaw/openclaw.json`

- [ ] Patch only the Gateway service with four environment mappings. Do not bind the NTFS/DrvFS source as a plugin path because OpenClaw rejects its world-writable mode.
- [ ] Add `.env` keys without printing values: enabled true, base URL `http://host.docker.internal:8790`, copied existing Core internal token, timeout seconds `10`.
- [ ] Pin `OPENCLAW_IMAGE` to the immutable ID/tag already running if the baseline Compose tag differs, then run `docker compose config` and inspect only sanitized image/env-name output.
- [ ] Pack the plugin with `npm pack`, install it through `openclaw plugins install npm-pack:<artifact>`, and set `plugins.entries.anh-duong-core.hooks.allowConversationAccess=true`.
- [ ] Recreate only `openclaw-gateway` from WSL with `--no-deps --force-recreate`; do not build, pull, remove volumes, or recreate CLI.
- [ ] Inspect the live runtime and require exactly three hooks, zero diagnostics, and safe managed-directory permissions.
- [ ] Re-hash the protected Telegram/model/provider/9Router config subsets and prove they equal the baseline hashes.
- [ ] Confirm the active image ID and package version remain unchanged.

## Task 7: Automated runtime verification and failure drills

**Files:**
- Create: `scripts/verify_tg1_runtime.ps1`
- Append: `F:\AIOS\anh-duong-checkpoints\TG-1-runtime.log`

- [ ] Implement a read-only verifier that reports sanitized PASS/FAIL rows for Core health/ready, Gateway health, Telegram live probe, plugin runtime inspection, active image/version, Alembic `0003`, worker false, Core reachability from Gateway, and protected config hashes.
- [ ] Run the verifier in happy-path mode.
- [ ] Prove fail-closed without a Telegram message by invoking registered hooks in the plugin tests for timeout, connection refusal, 401/403, non-2xx, malformed body, ID mismatch, and missing config; assert no model-pass decision.
- [ ] Temporarily run the verifier with `ANH_DUONG_CORE_ENABLED=false` only in a test process, proving explicit rollback bypass without mutating production.
- [ ] Search Gateway logs for plugin load errors and secret patterns using only hashes/redacted match counts.

## Task 8: Manual real Telegram gate

- [ ] Ask the operator to send exactly these two messages to the configured bot after runtime activation:

```text
Tóm tắt trạng thái hệ thống hiện tại
Tạo task kiểm tra backup tối nay
```

- [ ] Wait for both replies; do not declare PASS before they arrive.
- [ ] Correlate Telegram/OpenClaw and Core audit logs by the `tg-<runId>` request ID. Record timestamps, request IDs, route/capability, HTTP status, and final delivery outcome only.
- [ ] Confirm the first request is a read/direct-class route and the second is a workflow-class route with `execution_required=true`, unless the live Core router deterministically classifies otherwise; any unexpected route requires evidence and remediation, not hand-waving.
- [ ] Confirm one final reply per message, no direct-model bypass, and no token/chat/sender/session content in evidence.

## Task 9: Full regression and invariant checks

**Files:**
- Test only: Core and OpenClaw/plugin suites

- [ ] Core: `python -m pytest -q`.
- [ ] Core: `python -m ruff check .`, `python -m mypy app`, and `python -m compileall -q app` using the repository's configured environment/tooling.
- [ ] Plugin: `node --test integrations/openclaw-anh-duong-core/test/*.test.js` and syntax checks.
- [ ] OpenClaw targeted Telegram dispatch test and native-command/session suite; compare the known pre-existing three Windows path failures instead of misreporting them as TG-1 regressions.
- [ ] Run any supported OpenClaw lint/type/build checks that do not require upgrading host Node 24.14.0; record the pre-existing engine requirement of Node 24.15+ as a residual baseline risk.
- [ ] Re-run runtime verifier and compare pre/post image ID, Core migration head, worker state, and protected hashes.

## Task 10: Artifacts, rollback proof, and final verdict

**Files:**
- Create: `F:\AIOS\anh-duong-checkpoints\TG-1-report.md`
- Create: `F:\AIOS\anh-duong-checkpoints\TG-1-artifacts.zip`
- Include: implementation files, tests, sanitized runtime log, design, plan, report, diffs, hashes, and rollback instructions

- [ ] Write the report with changed files, exact verification commands, actual results, manual message evidence, preserved invariants, residual risks, and next recommendation.
- [ ] Write rollback steps: set enabled false for immediate legacy mode, or restore backed-up Compose/`.env`/`openclaw.json`, recreate only Gateway, and re-run verifier. Do not execute rollback after a successful deployment.
- [ ] Validate every ZIP path against an explicit allowlist; scan staged text for token/header/secret patterns and exclude secret-bearing backups from the ZIP.
- [ ] Create the ZIP, list contents, compute SHA-256, and verify extraction into a temporary directory under `F:\AIOS\anh-duong-core\.tmp_verify` without overwriting workspace files.
- [ ] Only after all automated checks and both live Telegram messages pass, issue final verdict `PASS`; otherwise remediate and rerun until deterministic evidence supports PASS or report a concrete unrecoverable blocker as `FAIL`.
