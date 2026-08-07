# Blocked by Core

## Symptoms
Core Gate safe message or a blocked model run.

## Known boundaries
**FACT:** fail-closed blocking must not be weakened.

## Evidence to collect
Runtime audit, route/capability, prepared state, health, and real request trace.

## Common false conclusions
Health 200 alone is not request proof.

## Confirmed root causes
**UNKNOWN:** no universal root cause.

## Safe diagnostic workflow
Diagnose read-only, then use a scoped repair.

## Minimal repair patterns
**PROPOSAL:** repair the proven integration boundary only.

## Validation gates
Targeted test, regression, and real E2E when integrated.

## Rollback notes
Use checkpoint backup.

## Related checkpoints
AD-IMG-2, AD-TXT-1.

## Last verified date
2026-08-06.
