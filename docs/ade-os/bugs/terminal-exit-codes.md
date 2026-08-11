# Terminal exit codes

## Symptoms
A diagnostic, test, or ADE command exits non-zero or reports an unexpected status.

## Known boundaries
**FACT:** a non-zero process exit means the invoked process did not report success. It does not by itself identify the failing component or root cause.

**INFERENCE:** an exit code should be correlated with the command, stderr, environment, and any affected runtime boundary before selecting a repair.

## Evidence to collect
Capture the exact command, exit code, redacted stdout/stderr, working directory, interpreter path, and relevant correlation ID. Preserve long output in the configured checkpoint artifact path.

## Common false conclusions
**FACT:** exit code `0` proves only that the process reported success; it is not proof of a real runtime request or checkpoint closure.

**PROPOSAL:** do not treat a shell wrapper's exit code as the underlying program result until the wrapper behavior is verified.

## Confirmed root causes
**UNKNOWN:** there is no universal mapping from an exit code to a root cause.

## Safe diagnostic workflow
Run the smallest read-only reproduction, record its result, and inspect the immediate error before widening scope. Do not suppress failures with `|| true` in evidence commands unless the captured status is retained.

## Minimal repair patterns
**PROPOSAL:** repair only the evidenced command, environment, or integration boundary; retain a targeted regression test when the failure is repeatable.

## Validation gates
Re-run the failed command with the same inputs, then the relevant targeted test and runtime/E2E check when the boundary is integrated.

## Rollback notes
Restore the timestamped backup of any changed persistent target; do not use a successful exit code as a substitute for rollback evidence.

## Related checkpoints
ADE-OS.

## Last verified date
2026-08-06.
