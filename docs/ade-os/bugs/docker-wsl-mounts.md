# Docker and WSL mounts

## Symptoms
A path, file, socket, configuration, or artifact is visible on the host but unavailable, stale, or permission-denied in Docker or WSL.

## Known boundaries
**FACT:** runtime health, mounts, and active container configuration are stronger evidence than a path documented elsewhere.

**FACT:** the active Core source is `/home/thadc/AIOS/anh-duong-core`; `/mnt/f/AIOS/anh-duong-core` is not an active runtime dependency.

**INFERENCE:** host/container or Windows/WSL path translation can cause a mount to resolve to a different location than the operator expects.

## Evidence to collect
Capture redacted `pwd`, mount/volume configuration, container inspection, ownership/mode, file hashes on both sides, service configuration, and the exact path observed by the affected process.

## Common false conclusions
**FACT:** a file existing on the host does not prove it is mounted into the running container or visible to the WSL process.

**PROPOSAL:** do not recreate or delete a mount target before proving which runtime owns it.

## Confirmed root causes
**UNKNOWN:** no universal mount root cause is established by a path mismatch alone.

## Safe diagnostic workflow
Compare the active process path with the host path, inspect the running mount configuration read-only, and verify access with a non-mutating command.

## Minimal repair patterns
**PROPOSAL:** correct only the evidenced mount declaration or ownership boundary after approval; do not alter Core runtime configuration as an ADE-OS repair.

## Validation gates
Verify the exact file/hash from the running boundary, then run the affected integration flow and preserve unrelated mounts.

## Rollback notes
Restore the timestamped configuration backup and re-verify the active mount state.

## Related checkpoints
ADE-OS, AD-IMG-2.

## Last verified date
2026-08-06.
