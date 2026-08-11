# Timeout and worker lease

## Symptoms
An asynchronous task times out, remains leased, appears duplicated, or is recovered unexpectedly by a worker.

## Known boundaries
**FACT:** worker lifecycle and lease observations must be correlated with the active runtime service and database, not inferred from source alone.

**FACT:** ADE-OS does not edit runtime DB state, migrations, or worker configuration.

**INFERENCE:** timeout, lease expiry, worker crash, clock mismatch, and recovery logic can produce similar task symptoms.

## Evidence to collect
Capture task/run IDs, enqueue/start/heartbeat/lease timestamps, worker identity, timeout configuration, recovery events, redacted logs, and read-only runtime DB observations from the confirmed live path.

## Common false conclusions
**FACT:** a completed worker process does not prove that a task lease was released correctly.

**PROPOSAL:** do not manually clear leases or mutate task rows during diagnosis.

## Confirmed root causes
**UNKNOWN:** no root cause is established until timeline evidence identifies the first divergent state transition.

## Safe diagnostic workflow
Build a timestamped lifecycle timeline, compare service logs with read-only task/run state, and reproduce only in a scoped safe environment when necessary.

## Minimal repair patterns
**PROPOSAL:** make the smallest approved correction to the proven timeout, heartbeat, recovery, or state-transition boundary.

## Validation gates
Run the focused worker test, relevant async-task regression, and a real runtime/E2E task lifecycle when integration behavior changed.

## Rollback notes
Restore the pre-change persistent target from its timestamped backup; never roll back by editing live task rows.

## Related checkpoints
CE-0R.

## Last verified date
2026-08-06.
