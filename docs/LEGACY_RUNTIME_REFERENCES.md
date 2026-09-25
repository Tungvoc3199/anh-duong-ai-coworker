# Legacy runtime references

The following files are historical checkpoint evidence/helpers and are not current
production runbooks:

- `scripts/deploy_recovery_approval_replay.py`
- `scripts/deploy_runtime_task_reliability.py`
- `scripts/verify_tg1_runtime.ps1`
- files under `artifacts/` and frozen release trees

These files may intentionally contain the endpoint, container name, release name, or
path that was correct for the checkpoint they certify. Do not rewrite historical
evidence merely to match today's runtime.

For current production facts, run:

```bash
/usr/local/libexec/anh-duong/runtime-truth
```

Current operational code and documentation must not derive production truth from a
historical file or hardcoded endpoint.
