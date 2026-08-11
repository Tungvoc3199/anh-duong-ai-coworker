# Regression failures

## Symptoms
A targeted repair passes its direct check but a related unit, integration, regression, or end-to-end test fails.

## Known boundaries
**FACT:** a checkpoint cannot be closed from file creation, a unit test, or health status alone when broader applicable gates lack evidence.

**INFERENCE:** a regression may be caused by the repair, a pre-existing failure, environment drift, fixture assumptions, or an unrelated concurrent modification until baseline evidence separates them.

## Evidence to collect
Record the exact test command, interpreter/environment, failure output, baseline status when available, changed-file diff scope, test selection rationale, and runtime/E2E trace for integrated changes.

## Common false conclusions
**FACT:** a passing targeted test does not prove regression coverage.

**PROPOSAL:** do not broaden or refactor unrelated code merely to make a regression suite pass.

## Confirmed root causes
**UNKNOWN:** a failed regression is not attributable to the current change without a reproducible comparison and scoped diff evidence.

## Safe diagnostic workflow
Reproduce the smallest failure, compare it to a known baseline or pre-existing evidence, inspect the narrow changed boundary, and escalate unresolved causality to Deep Debug.

## Minimal repair patterns
**PROPOSAL:** repair only the evidenced regression boundary, preserving unrelated modifications and adding a focused test only when essential.

## Validation gates
Run the original failing test, the targeted test, relevant regression, and runtime/E2E verification when the repair changes an integration boundary. Obtain independent review before closure.

## Rollback notes
Restore the timestamped backup for the repaired target and retain the failure evidence for comparison.

## Related checkpoints
ADE-OS.

## Last verified date
2026-08-06.
