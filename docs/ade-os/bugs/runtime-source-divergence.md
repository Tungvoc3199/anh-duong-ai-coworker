# Runtime and source divergence

## Symptoms
A source edit, test result, or repository file does not match the behavior of the running service.

## Known boundaries
**FACT:** active source is `/home/thadc/AIOS/anh-duong-core`.

**FACT:** the service is `anh-duong-core.service` and the active endpoint is `http://127.0.0.1:8790`.

**FACT:** `/mnt/f/AIOS/anh-duong-core` is not an active runtime dependency.

**INFERENCE:** a stale process, different checkout, container image, generated artifact, or un-reloaded configuration may explain divergence after the active boundary is verified.

## Evidence to collect
Record service unit/process details, executable and working directory, active mounts/container configuration, source revision/hash, loaded module path, endpoint response, timestamps, and redacted logs.

## Common false conclusions
**FACT:** changing a file under `/mnt/f/AIOS/anh-duong-core` does not repair the active source runtime.

**PROPOSAL:** do not restart or redeploy a service merely because source and behavior differ.

## Confirmed root causes
**UNKNOWN:** divergence remains unproven until source and active runtime identity are compared directly.

## Safe diagnostic workflow
Inspect the live process and service configuration read-only, then compare its source/artifact identity with the active checkout and endpoint behavior.

## Minimal repair patterns
**PROPOSAL:** change only the verified active deployment/source boundary after the checkpoint scope authorizes it.

## Validation gates
Confirm the loaded active version and repeat the affected runtime request; use targeted regression and E2E evidence where applicable.

## Rollback notes
Restore the timestamped backup or approved prior deployment artifact, then re-check the active process identity.

## Related checkpoints
ADE-OS, AD-IMG-2.

## Last verified date
2026-08-06.
