# Checkpoint gate evidence

**Symptoms:** A closure was requested with missing test, rollback, or independent review evidence.

**Diagnosis:** Closure is not a status inferred from file creation or health alone.

**Resolution:** Record `conflict_gate`, `scoped_diff`, `tests`, `backup`, and
`rollback` as `true`; then obtain a read-only `review: "PASS"`. The ADE close gate
must otherwise return `BLOCKED` and list the missing evidence.
