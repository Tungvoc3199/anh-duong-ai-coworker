# Provider authentication and quota

## Symptoms
A provider request reports authentication, authorization, quota, rate-limit, OAuth, API-key, model-availability, or `401`/`403`/`429` failure.

## Known boundaries
**FACT:** credentials, authorization values, tokens, cookies, and private keys must never be exposed in diagnostics or artifacts.

**FACT:** provider routing and model configuration are protected Core surfaces and are not changed by ADE-OS.

**INFERENCE:** `401`, `403`, and `429` can distinguish authentication, authorization, and quota/rate-limit classes only when supported by the provider's redacted response evidence.

## Evidence to collect
Record provider name, model identifier, timestamp, redacted status/error body, request correlation ID, configured credential presence (never its value), account authorization state, quota/rate-limit metadata, and any verified fallback.

## Common false conclusions
**FACT:** a healthy local service does not prove that an external provider accepted a request.

**PROPOSAL:** do not rotate secrets, alter providers, or select a fallback merely because a request failed once.

## Confirmed root causes
**UNKNOWN:** no provider-specific root cause is established without redacted provider evidence.

## Safe diagnostic workflow
Classify the redacted failure, verify configuration presence without reading secret values, and compare it with provider status and account evidence. Keep the investigation read-only until a separately approved repair exists.

## Minimal repair patterns
**PROPOSAL:** apply the smallest approved credential, authorization, quota, or availability correction outside ADE-OS; preserve prior routing until the repair is verified.

## Validation gates
Use a scoped redacted request, confirm the expected provider/model response, and run affected integration/E2E checks without disclosing authorization material.

## Rollback notes
Use the checkpoint backup and approved configuration rollback. Never place credentials in a rollback artifact.

## Related checkpoints
AD-IMG-2, AD-TXT-1.

## Last verified date
2026-08-06.
