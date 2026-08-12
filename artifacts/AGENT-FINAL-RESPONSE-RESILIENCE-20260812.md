# Agent Final Response Resilience — 2026-08-12

## Verdict

- Regression evidence: CONFIRMED from Telegram screenshot: workflow ACK followed by `OpenClaw returned an invalid execution result contract.`
- Root cause: CONFIRMED in GitHub `main` source at baseline `9e44adfde276ef687dfc86087e394876f83b77b0`.
- Isolated source repair: PASS.
- Branch-equivalent focused tests: PASS, 22/22.
- Python compile check for changed Python files: PASS.
- Production activation: NOT PERFORMED.
- Real Telegram production E2E after this repair: NOT PERFORMED.

## Root cause

`OpenClawExecutor` treated the agent's final content and optional execution metadata as one strict Pydantic contract. Useful agent replies were therefore discarded when JSON metadata was merely shaped differently from the expected schema. Existing tests explicitly encoded rejection for partial known-looking metadata and unknown outcome values.

This produced inconsistent user experience:

- plain non-JSON `output_text` was converted into `outcome=completed` and delivered;
- JSON with a useful answer but an unrecognized/missing outcome or partial `artifacts`/`verification` could raise `invalid_response_contract`;
- the worker then terminalized the run and Telegram received the internal contract error instead of the agent's useful final answer.

## Repair

1. Keep transport/envelope errors fail-closed.
2. Normalize model-produced result content at the OpenClaw boundary before validating it.
3. Preserve a user-facing final from `summary`, `answer`, `final_answer`, `message`, `response`, `text`, or `content`.
4. Normalize common outcome aliases (`success`, `done`, `error`, approval states, etc.).
5. Preserve generic `artifacts` and `verification` dictionaries when they only partially resemble a known typed schema.
6. Normalize non-critical metadata (`files_changed`, `commands_run`, `tests`, `duration_ms`) instead of rejecting the entire final answer.
7. Treat an explicitly unknown outcome conservatively as `failed` while still preserving and delivering the final text.
8. Add a last-resort validation fallback that returns a terminal `failed` result with the preserved final summary rather than raising `invalid_response_contract` for model-produced result content.
9. Strengthen the execution instruction: always return a final user-facing answer; structured metadata is secondary.
10. Preserve secret redaction when a final summary must be synthesized from structured content.

## Focused tests

Covered:

- canonical CE-2 structured result;
- real workflow object result;
- read-only health/ready object result;
- partial known-looking artifacts;
- answer-only JSON;
- error-status JSON with useful message;
- JSON array output;
- non-critical metadata with alternate types;
- success outcome alias;
- unknown outcome with preserved final;
- normalized fallback secret redaction;
- HTTP error classification;
- timeout semantics.

Branch-equivalent local result: `22 passed`.

## Safety / scope

No production service, DB, schema, migration, provider, token, model routing, cache, Telegram config, or OpenClaw Gateway runtime was changed by this source repair. Production remains untouched until a controlled activation and one real Telegram workflow E2E are performed.
