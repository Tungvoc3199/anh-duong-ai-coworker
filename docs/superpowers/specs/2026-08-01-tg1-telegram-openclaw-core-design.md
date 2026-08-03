# TG-1 Telegram → OpenClaw → Ánh Dương Core Design

## Status and scope

This design implements the already-approved TG-1 architecture without changing the Core database schema, OR-1 contract, model/provider/9Router configuration, Telegram token, or async-worker state. It covers ordinary Telegram AI turns only. Native/admin commands and ambient room events remain on their existing OpenClaw paths.

## Contract findings

`POST /api/internal/requests/prepare` accepts only `text`, optional `request_id`, `channel`, `actor`, and optional Project/Task/Memory identifiers. It returns an immutable `PreparedRequest`; it does not execute tools or enqueue work. The fields consumed by OpenClaw are:

- `request_id` for end-to-end correlation;
- `normalized_text` as the redacted current request;
- `route_decision` and `capability_decision` as the Core routing decision;
- `context.rendered_context` as the prepared execution context;
- `execution_required` to distinguish workflow preparation;
- `warnings`, provenance, Persona reference, and UTC creation time for validation/audit.

Telegram chat, topic, sender, and OpenClaw session fields cannot be added to the JSON body because the Core model forbids unknown fields. The adapter therefore derives a deterministic, non-reversible request ID from account/chat/topic/message/session identifiers and maps a non-reversible sender hash into `actor`. The original Telegram metadata stays inside OpenClaw and is used by the existing delivery pipeline.

## Approaches considered

1. **Runtime-matched managed OpenClaw plugin — selected.** Package a dependency-free JavaScript plugin as a local npm tarball, install it into OpenClaw's permission-safe managed ext4 plugin directory, and register the public `before_prompt_build`, `before_agent_run`, and `agent_end` hooks. The plugin scopes itself to `messageProvider/channel === "telegram"`, so other channels are unchanged. This preserves the established Telegram transport, durable ingress, native-command fast path, session, model/tool execution, streaming, and reply funnels without rebuilding or upgrading the running image.
2. **Patch the bundled Telegram extension — rejected for this runtime.** The checked-out OpenClaw source is 2026.7.2 while the active image is 2026.7.1. Rebuilding the checkout would silently upgrade the deployed runtime; patching its generated 2026.7.1 bundle would be fragile and unreviewable.
3. **New Core execution endpoint or worker — rejected.** OR-1 is deliberately prepare-only and Async Worker must remain false. Adding execution semantics would change the approved architecture and contract.

## Components

### Local plugin and Core client

- Lives in `integrations/openclaw-anh-duong-core` and ships a native plugin manifest, an ESM entrypoint, and dependency-free client/validation modules tested with Node's built-in test runner.
- Loads `ANH_DUONG_CORE_ENABLED`, `ANH_DUONG_CORE_BASE_URL`, `ANH_DUONG_CORE_INTERNAL_TOKEN`, and `ANH_DUONG_CORE_TIMEOUT_SECONDS` from the process environment.
- Treats absent/false `ENABLED` as an explicit rollback/legacy mode. When enabled, missing or malformed configuration fails closed.
- Builds the minimal `CoreRequest` from the finalized OpenClaw agent prompt and hook context. `request_id` is derived from the per-turn `runId`; `actor` is a non-reversible sender hash.
- Calls the protected endpoint with a finite timeout and one bearer-authenticated POST. It performs no retries, avoiding duplicate preparation/audit or downstream execution.
- Validates every response field consumed by OpenClaw and verifies route/execution consistency and request-ID equality.
- Classifies failures as configuration, timeout, connection, authentication, HTTP, or validation errors without retaining response bodies or secrets.
- Produces a Core-prepared agent prompt containing the validated rendered context and routing metadata.

### Hook integration

- `before_prompt_build` is the only network phase. For an eligible Telegram agent turn it marks the `runId` fail-closed, calls Core, validates the response, records sanitized state, and returns `prependContext` only after success.
- `before_agent_run` checks the state for the same `runId`. It returns `pass` only after a validated Core preparation. Missing, failed, timed-out, or malformed state returns `block` with the safe user-facing message, so no model input occurs.
- `agent_end` clears per-run state; an expiry sweep bounds abandoned state. No state contains raw prompt, chat ID, sender ID, session key, token, or response body.
- Explicit disabled mode returns no hook result and preserves the legacy path. Native/admin commands already complete before agent invocation, so they never enter these hooks. Ambient or non-Telegram turns are ignored.

## Data flow

| Telegram/OpenClaw input | Core request | Core response | OpenClaw action |
|---|---|---|---|
| finalized agent-turn prompt | `text` | `normalized_text`, `context.rendered_context` | Prepend validated Core context before model execution |
| OpenClaw per-turn `runId` | bounded `tg-<runId>` `request_id` | matching `request_id` | Structured correlation log and hook gate |
| sender ID | hashed `actor` | audit actor only | Raw sender ID remains local |
| channel | `channel="telegram"` | audit channel | Existing Telegram delivery |
| no inferred registry IDs | omit optional IDs | optional IDs remain null | No registry guessing |
| existing session/chat/thread context | not sent (contract forbids metadata) | not returned | Preserved unchanged by the existing OpenClaw runtime |
| route/capability decision | n/a | validated decision | Included in prepared prompt for existing model/tool runtime |

Direct, memory, and Core-read routes run through the normal OpenClaw agent runtime with Core-prepared context. Workflow routes also use that runtime, with `execution_required=true`; no async worker or new workflow engine is introduced.

## Failure and security behavior

- Enabled Core integration is fail-closed for timeout, connect, 401/403, other non-2xx, invalid JSON, response validation, request-ID mismatch, and invalid local configuration.
- The user receives: `Ánh Dương Core hiện chưa sẵn sàng xử lý yêu cầu này. Vui lòng thử lại sau.`
- Logs contain request ID, failure class, HTTP status when available, route/capability on success, and no raw token, Authorization header, raw response body, chat ID, sender ID, or session key.
- There is no CLI fallback and no direct-model fallback.
- Disabled mode is explicit and supports rollback to the pre-TG-1 behavior.

## Runtime configuration

The Gateway container receives the four TG-1 environment variables through the existing Compose service. Runtime activation uses `http://host.docker.internal:8790`, which has been verified from inside the current Gateway container. The existing internal Core token is copied without printing it. The package is installed with `plugins install npm-pack:...`, its ID is added to the existing allowlist/enabled entries, and `hooks.allowConversationAccess=true` authorizes only the two conversation hooks required by the gate. A direct NTFS bind is intentionally not used because OpenClaw correctly rejects world-writable plugin paths. Only the Gateway service is recreated from WSL; no build, image/version update, or volume deletion is allowed.

## Testing and verification

TDD starts with Node built-in unit/integration tests for configuration, request mapping, deterministic correlation, bearer use/redaction, direct/workflow response mapping, timeout/auth/HTTP/invalid-response fail-closed behavior, disabled/non-Telegram behavior, prompt construction, hook ordering, and per-run cleanup. A hook integration test proves failure makes `before_agent_run` return a blocking decision before model input; OpenClaw's own hook contract supplies the existing single final reply funnel.

Regression includes the targeted Telegram adapter/dispatch/native-command suites, TypeScript checks, lint/build scripts supported by the installed Node runtime, and the full Core Pytest/Ruff/Mypy/Compileall suite. Runtime verification checks Core health/ready, Gateway health, Telegram probe, Alembic `0003`, Async Worker false, and pre/post configuration hashes. Final PASS additionally requires the operator's two real Telegram messages and cross-log evidence.

## Rollback

Set `ANH_DUONG_CORE_ENABLED=false` for the reversible legacy path, or restore the backed-up Compose, `.env`, and `openclaw.json` files, uninstall the managed plugin if a full removal is desired, recreate only the Gateway service from WSL, and re-run Gateway/Telegram/Core health checks. No database, image, or volume rollback is required.
