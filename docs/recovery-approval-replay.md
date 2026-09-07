# Approval replay on restart
FACT: restart at 2026-09-07 00:17:09 UTC requeued 33 old approval-blocked runs.
They were blocked again and notifications were resent after startup, ending at 00:17:46 UTC.
No new user request was needed. Pending notification count is now zero.
Root cause: recover_stale_runs treated policy allowed_with_step_gates as permission to
manual_retry every legacy approval_required run. manual_retry resets delivery state;
the plan approval gate blocks the same goal again, and the notification worker sends again.
This repeats at each startup while the legacy selection still matches.

Fix: recovery handles stale leases only. A durable blocked approval is never automatically
retried due to restart or policy re-evaluation. Owner approval/continuation APIs retain
ownership of that transition. Existing tasks, approvals and delivery receipts are preserved.
No bulk approval, deletion, Telegram deletion, or live DB edits.

RED: old behavior requeued the sent blocked approval.
GREEN: repeated recovery leaves run blocked, notification sent and row version unchanged.
Regression includes startup lifespan, workers, plan orchestration, service, API corrections
and notification retries. Exact output in checkpoint regression.log.
Candidate requires authorized Core service cutover. No gateway/plugin/model changes.

Verification: 79 regression tests PASS. Two recovery calls against a temporary copy of all 253 production runs changed no state or notification and requeued zero tasks. Initial snapshot harness correctly required the existing HMAC configuration; validated using the running service keyring without printing secrets.
