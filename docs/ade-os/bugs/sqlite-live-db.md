# SQLite live database

## Symptoms
A database query, schema observation, or state expectation differs between a local file and the running service.

## Known boundaries
**FACT:** the runtime database is `/home/thadc/.local/state/anh-duong-core/anh_duong.db`.

**FACT:** ADE-OS must not edit the runtime database, schema, or migrations.

**INFERENCE:** a copied, alternate, or stale SQLite file can produce observations that do not represent live service state.

## Evidence to collect
Record the queried absolute path, read-only connection mode, file metadata/hash where safe, active service configuration, relevant migration version, query text, and redacted results.

## Common false conclusions
**FACT:** inspecting a repository-local `.db` file does not prove anything about the configured runtime database.

**PROPOSAL:** do not infer a schema defect from a failed write attempted against a read-only or locked database.

## Confirmed root causes
**UNKNOWN:** state divergence, locking, schema mismatch, and query scope require separate evidence.

## Safe diagnostic workflow
Confirm the runtime DB path, use read-only inspection, compare migration/version evidence, and correlate results with service logs and health.

## Minimal repair patterns
**PROPOSAL:** hand off an evidenced database or migration repair for explicit approval; ADE-OS records evidence only.

## Validation gates
Run read-only verification against the confirmed runtime DB and the affected service path. Include a regression/E2E check if an approved runtime repair occurred.

## Rollback notes
Use a timestamped backup created before an approved database change. Do not overwrite the live DB as part of diagnosis.

## Related checkpoints
CE-0R, ADE-OS.

## Last verified date
2026-08-06.
