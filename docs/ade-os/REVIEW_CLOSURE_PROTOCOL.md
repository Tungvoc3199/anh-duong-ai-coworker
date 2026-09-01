# ADE Review / Closure Protocol

Checkpoint: `AD-REVIEW-CLOSURE-PROTOCOL`

Purpose: bound independent review, make the reviewed candidate immutable, and fail closed when review/test/merge evidence is stale. Review quality is not reduced; repeated semantic review is replaced by adversarial batching plus one bounded re-review.

## Phase 0 — source truth / conflict gate

Before mutation, freshly verify canonical `main`, `origin/main`, dirty state, active checkpoint, parallel worktrees, process CWDs, relevant runtime truth, and artifact directory. A real ownership/process conflict blocks mutation. Never reset, stash, clean, remove, or kill another lane to make the gate pass.

## Phase 1 — unit execution

For each root-cause unit:

1. RED reproduction.
2. Minimal implementation.
3. GREEN focused test.
4. Focused regression.
5. Self/adversarial review.

Do not invoke the independent final reviewer after each tiny fix. Adjacent variants of one root cause belong in one adversarial matrix.

## Phase 2 — candidate build

A candidate exists only when all known units are GREEN, targeted tests and static checks pass, no known finding is open, and the diff is in scope. Record the base SHA, intended candidate SHA, changed files, and candidate generation.

## Phase 3 — pre-final adversarial sweep

Before final review, probe the original root cause, same-class bypasses, boundaries, fail-open/fail-closed behavior, and interactions with existing governance. This is a deterministic test sweep, not a second semantic reviewer.

## Phase 4 — lock candidate

1. Stage the exact candidate and run `git diff --cached --check`.
2. Save the canonical candidate diff: `git diff --binary --full-index <base>..<candidate>` after committing the exact staged tree.
3. SHA256 that exact byte stream and record it as `locked_diff_sha256`.
4. Require a clean worktree and immutable candidate commit.
5. Run review/close through ADE with the candidate worktree/main as an explicit `--root`; ADE recomputes HEAD, cleanliness and the canonical diff hash from Git. The CLI must BLOCK `review`/`close` when `--root` is omitted rather than inferring a repository or falling back to JSON-only trust.

Any source edit or new commit invalidates the lock. Create a new generation and rerun affected gates before another semantic review.

## Phase 5 — one independent final review

The reviewer reads only current source/diff for the exact lock and probes candidate-level P0/P1/P2. Historical verdicts are excluded to avoid anchoring. Unrelated repository debt, intentionally stronger fail-closed behavior, and unavailable runtime outside the review contract are not candidate findings.

Formal output is required:

```text
P0=<n> P1=<n> P2=<n>
<findings or No blocking findings.>
VERDICT: PASS|BLOCKED
```

PASS means exactly `P0=0`, `P1=0`, `P2=0`, `reviewer_independent=true`, reviewer status `COMPLETED`, and formal verdict `PASS`. Timeout/quota/auth/harness failure is not PASS and increments only `tool_failures`; retry may review the same lock without consuming another semantic review round.

## Finding batch / review budget

If final review finds a defect, classify its root-cause class, search adjacent variants, create one finding batch, TDD the whole batch, rerun adversarial/targeted/static/full gates on the new source generation, lock a new candidate, then perform one re-review.

`final_review_count` is bounded to 2. Round 2 is allowed only with `rereview_reason="finding_batch"`, a non-empty string `finding_batch_id`, batched findings, and fresh full regression after that batch. A third semantic review is a protocol violation; return to design/root-cause work instead of reviewer ping-pong.

## Freshness generations

Every behavior-changing source batch increments `source_generation`. The following must equal that generation before final review/close:

- `adversarial_generation`
- `targeted_generation`
- `static_generation`
- `full_regression_generation`
- `review_generation`

This makes tests/review performed before the last source mutation machine-detectably stale. Tool failures do not change source generation.

## Full regression policy

Do not run the full suite after every tiny fix. Run it at candidate gate, after a final-review finding batch, and post-merge for the exact final candidate. A claimed baseline failure requires a fresh baseline comparison; memory alone is not evidence.

## Merge identity

Final merge is `--ff-only`. No force push. At close, `merge_sha` must equal `reviewed_sha` and `merge_diff_sha256` must equal `reviewed_diff_sha256`. ADE also verifies the actual repository HEAD and canonical diff hash. Main/origin drift requires reconciliation and rerunning affected gates; it is never solved by rewrite.

## Runtime truth

`runtime_mode` is explicit:

- `SOURCE_ONLY`: source/governance checkpoint. Deployment is not required. `deployed=false` and `runtime_e2e=false` are truthful and valid.
- `RUNTIME_REQUIRED`: new-code production behavior is part of the checkpoint contract. Closure requires `deployed=true` and `runtime_e2e=true`.

`deployed` and `runtime_e2e` are strict booleans. `runtime_e2e=true` is invalid unless `deployed=true`; source-only closure may truthfully use both false.

If a source-only checkpoint is not deployed, health/ready/PID/DB checks may describe the existing process but never prove the new source is loaded.

## Closure evidence

`closure_review` is required for `checkpoint review` and `checkpoint close`. It carries immutable Git identity, diff hashes, freshness generations, formal review verdict/severity counts, review budget/finding batch metadata, and runtime mode. The gate fails closed for malformed or stale evidence.

A closure artifact must additionally record checkpoint/base/final SHA, locked diff hash, tests/static results, independent review output, merge/push evidence, runtime/deploy truth, exclusions, authoritative checkpoint close result, and final lane audit.

## Resource governance

Focused tests may run with other lanes. Full suites and final merges are serialized. Never mutate files/worktrees/processes owned by another lane; a required cross-lane file becomes an explicit dependency instead of a hidden overwrite.
