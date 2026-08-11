# External runtime-memory CLI unavailable

**Symptoms:** An external memory query exits non-zero, times out, or cannot be spawned.

**Diagnosis:** ADE has no authority to infer runtime memory from an unavailable CLI.

**Resolution:** Treat the result as unavailable, preserve the error evidence, and do
not fall back to runtime DB writes, provider calls, or unbounded shell execution.
