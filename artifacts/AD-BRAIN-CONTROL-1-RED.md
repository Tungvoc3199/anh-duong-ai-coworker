# AD-BRAIN-CONTROL-1 — RED

Expected pre-fix behavior from source inspection:

- `Mở Chrome thông qua OpenClaw như nào?` matches advisory language and falls through to DIRECT.
- DIRECT maps to `CONVERSATIONAL_RESPONSE`.
- The OpenClaw integration returns `undefined` for non-workflow prepared state, allowing the agent to own the final reply.

The regression tests in `tests/unit/test_ad_brain_control_1.py` encode the desired behavior and are expected to fail before the production-code change.

Runtime/CI execution evidence is still required before claiming RED verified.
