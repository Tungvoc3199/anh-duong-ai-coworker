# Media understanding

## Symptoms
A Telegram image or other media request is not understood, loses its caption/envelope, selects an unsuitable model, or fails before a Core response.

## Known boundaries
**FACT:** AD-IMG-2 recorded an OpenClaw configuration inventory, plugin/media inventory, plugin inventory, vision inventory, 9Router inventory, runtime log, diff, and closure artifacts under `/mnt/f/AIOS/anh-duong-checkpoints`.

**FACT:** AD-IMG-2's diagnostic boundary is `Telegram ingestion → OpenClaw media-understanding → provider/model → multimodal payload → Core classification → response`.

**FACT:** AD-IMG-2 was recorded closed in `AD-IMG-2-CLOSED-20260805T195627Z.md`; this is checkpoint evidence, not proof that every future media request succeeds.

**INFERENCE:** a media failure can arise at any boundary in that chain and requires correlation across the same request before assigning cause.

## Evidence to collect
Collect media MIME/type and size, caption/envelope parsing, image-capability declaration, selected provider/model, payload shape, fallback decision, identity/state correlation, direct/workflow route, Task/Run creation, redacted logs, and a real request trace when approved.

## Common false conclusions
**FACT:** Core health alone is not proof of end-to-end image understanding.

**PROPOSAL:** do not change provider/model routing or send real media merely to diagnose an unscoped failure.

## Confirmed root causes
**UNKNOWN:** AD-IMG-2 artifacts establish the investigated boundaries, not a universal root cause for subsequent media incidents.

## Safe diagnostic workflow
Trace one correlated request through each boundary read-only. Verify MIME and payload facts before inferring model capability or fallback behavior. Redact all credentials and user content as required.

## Minimal repair patterns
**PROPOSAL:** repair only the proven ingestion, payload, capability declaration, route, or state-correlation boundary under an approved checkpoint.

## Validation gates
Run targeted tests, relevant regression, and a real end-to-end media request when the changed boundary integrates with runtime behavior.

## Rollback notes
Restore the checkpoint backup for the changed integration target and verify the prior route without altering provider configuration.

## Related checkpoints
AD-IMG-2.

## Last verified date
2026-08-06.
