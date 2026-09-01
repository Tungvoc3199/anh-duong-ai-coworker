# Review Closure Protocol

`AD-REVIEW-CLOSURE-PROTOCOL` prevents reviewer ping-pong while keeping closure fail-closed.

## Required execution order

1. Implement units with RED → fix → GREEN → local/self-review.
2. Run the adversarial/fuzz matrix before freezing the candidate.
3. Freeze one candidate SHA.
4. Run focused regression and full regression on that SHA.
5. Run one independent semantic closure review.
6. If findings exist, batch all actionable findings, repair them in one pass, rerun affected/focused/full gates, then run exactly one semantic re-review.
7. A third semantic review round is forbidden. Return to root-cause/design work or open a new checkpoint instead.
8. Tool/provider timeout, quota, auth, or harness failure does not consume a semantic review round; retry/fallback must review the same frozen SHA.
9. Any behavior-changing code edit after PASS makes the review stale. Formatting/evidence-only changes must not claim behavior equivalence without proof.
10. Merge/deploy only when the closure gate accepts the evidence.

## Machine-enforced evidence

`checkpoint review` and `checkpoint close` require `closure_review`:

```json
{
  "protocol_version": 1,
  "candidate_sha": "0123456789abcdef0123456789abcdef01234567",
  "reviewed_sha": "0123456789abcdef0123456789abcdef01234567",
  "candidate_frozen": true,
  "adversarial_matrix_passed": true,
  "focused_regression_passed": true,
  "full_regression_passed": true,
  "reviewer_independent": true,
  "semantic_review_rounds": 1,
  "findings_batched": true,
  "behavior_changed_after_review": false,
  "tool_failures": 0
}
```

`semantic_review_rounds` may be 1 or 2 only. `tool_failures` is tracked separately and does not consume review budget. `candidate_sha` and `reviewed_sha` must be the same full 40-character Git SHA, and that SHA must equal the repository HEAD independently resolved by the CLI at `checkpoint review` / `checkpoint close`.
Blocked `checkpoint review` and `checkpoint close` return process exit code `4`; PASS returns `0`. Callers must check both the exit code and JSON status.

## Fail-closed codes

- `CLOSURE_REVIEW_PROTOCOL_REQUIRED`: no protocol evidence.
- `CLOSURE_REVIEW_PROTOCOL_INVALID`: malformed or incomplete evidence.
- `REVIEW_CANDIDATE_UNBOUND`: repository HEAD cannot be independently resolved.
- `REVIEW_CANDIDATE_STALE`: reviewed/candidate SHA differs from each other or from repository HEAD, or behavior changed after review.
- `REVIEW_BUDGET_EXCEEDED`: more than two semantic review rounds.
- `REVIEW_FINDINGS_NOT_BATCHED`: re-review attempted without batching findings.
