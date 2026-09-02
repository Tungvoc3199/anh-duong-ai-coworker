from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from ade_os import core  # noqa: E402

SHA_A = "a" * 40
SHA_B = "b" * 40
DIFF_A = "1" * 64
DIFF_B = "2" * 64


def _review(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "protocol_version": 1,
        "base_sha": "0" * 40,
        "candidate_sha": SHA_A,
        "reviewed_sha": SHA_A,
        "merge_sha": SHA_A,
        "locked_diff_sha256": DIFF_A,
        "reviewed_diff_sha256": DIFF_A,
        "merge_diff_sha256": DIFF_A,
        "candidate_locked": True,
        "candidate_clean": True,
        "source_generation": 1,
        "adversarial_generation": 1,
        "targeted_generation": 1,
        "static_generation": 1,
        "full_regression_generation": 1,
        "review_generation": 1,
        "reviewer_independent": True,
        "reviewer_status": "COMPLETED",
        "review_verdict": "PASS",
        "p0": 0,
        "p1": 0,
        "p2": 0,
        "final_review_count": 1,
        "rereview_reason": None,
        "finding_batch_id": None,
        "findings_batched": True,
        "last_finding_batch_generation": None,
        "tool_failures": 0,
        "runtime_mode": "SOURCE_ONLY",
        "deployed": False,
        "runtime_e2e": False,
    }
    payload.update(overrides)
    return payload


def _evidence(**review_overrides: object) -> dict[str, object]:
    return {
        "checkpoint_id": "AD-REVIEW-CLOSURE-PROTOCOL",
        "conflict_gate": True,
        "scoped_diff": True,
        "tests": True,
        "backup": True,
        "rollback": True,
        "review": "PASS",
        "closure_review": _review(**review_overrides),
    }


def _close(**review_overrides: object) -> dict[str, object]:
    return core.validate_closure_review_protocol(_review(**review_overrides), action="close")


def _assert_blocked(code: str, **review_overrides: object) -> None:
    result = _close(**review_overrides)
    assert result["status"] == "BLOCKED"
    assert result["code"] == code


def test_source_change_after_review_blocks_close() -> None:
    _assert_blocked(
        "REVIEW_STALE_AFTER_SOURCE_MUTATION",
        source_generation=2,
        adversarial_generation=2,
        targeted_generation=2,
        static_generation=2,
        full_regression_generation=2,
        review_generation=1,
    )


def test_reviewer_timeout_without_formal_verdict_blocks() -> None:
    _assert_blocked(
        "FINAL_REVIEW_INCOMPLETE",
        reviewer_status="TIMEOUT",
        review_verdict=None,
    )


def test_any_p1_blocks() -> None:
    _assert_blocked("FINAL_REVIEW_FINDINGS_OPEN", p1=1, review_verdict="BLOCKED")


def test_candidate_must_be_locked() -> None:
    _assert_blocked("CANDIDATE_NOT_LOCKED", candidate_locked=False)


def test_locked_diff_hash_mismatch_blocks() -> None:
    _assert_blocked("LOCKED_DIFF_HASH_MISMATCH", reviewed_diff_sha256=DIFF_B)


def test_full_regression_before_last_source_mutation_blocks() -> None:
    _assert_blocked(
        "FULL_REGRESSION_STALE",
        source_generation=2,
        adversarial_generation=2,
        targeted_generation=2,
        static_generation=2,
        full_regression_generation=1,
        review_generation=2,
    )


def test_second_review_same_candidate_without_finding_batch_reason_blocks() -> None:
    _assert_blocked(
        "DUPLICATE_REVIEW_UNJUSTIFIED",
        final_review_count=2,
        rereview_reason=None,
    )


def test_finding_batch_fix_requires_fresh_full_regression() -> None:
    _assert_blocked(
        "FINDING_BATCH_FULL_REGRESSION_REQUIRED",
        source_generation=2,
        adversarial_generation=2,
        targeted_generation=2,
        static_generation=2,
        full_regression_generation=1,
        review_generation=2,
        final_review_count=2,
        rereview_reason="finding_batch",
        finding_batch_id="BATCH-1",
        last_finding_batch_generation=2,
    )


def test_reviewed_candidate_must_match_merge_candidate() -> None:
    _assert_blocked("MERGE_CANDIDATE_MISMATCH", merge_sha=SHA_B)


def test_reviewed_diff_must_match_merge_diff() -> None:
    _assert_blocked("MERGE_CANDIDATE_MISMATCH", merge_diff_sha256=DIFF_B)


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("adversarial_generation", "ADVERSARIAL_SWEEP_STALE"),
        ("targeted_generation", "TARGETED_REGRESSION_STALE"),
        ("static_generation", "STATIC_VALIDATION_STALE"),
    ],
)
def test_candidate_validation_must_follow_last_source_mutation(field: str, code: str) -> None:
    overrides: dict[str, object] = {
        "source_generation": 2,
        "adversarial_generation": 2,
        "targeted_generation": 2,
        "static_generation": 2,
        "full_regression_generation": 2,
        "review_generation": 2,
    }
    overrides[field] = 1
    _assert_blocked(code, **overrides)


def test_source_only_checkpoint_does_not_require_fake_runtime_e2e() -> None:
    result = _close(runtime_mode="SOURCE_ONLY", deployed=False, runtime_e2e=False)
    assert result["status"] == "PASS"


def test_runtime_required_checkpoint_requires_real_deploy_and_e2e() -> None:
    _assert_blocked(
        "RUNTIME_E2E_REQUIRED",
        runtime_mode="RUNTIME_REQUIRED",
        deployed=False,
        runtime_e2e=False,
    )


def test_runtime_required_checkpoint_passes_with_structured_runtime_evidence() -> None:
    result = _close(
        runtime_mode="RUNTIME_REQUIRED",
        deployed=True,
        runtime_e2e=True,
        runtime_evidence=_runtime_evidence(),
    )
    assert result["status"] == "PASS"


def test_one_batched_finding_rereview_is_allowed() -> None:
    result = _close(
        final_review_count=2,
        rereview_reason="finding_batch",
        finding_batch_id="BATCH-1",
        last_finding_batch_generation=1,
    )
    assert result["status"] == "PASS"


def test_third_semantic_review_is_blocked() -> None:
    _assert_blocked(
        "REVIEW_BUDGET_EXCEEDED",
        final_review_count=3,
        rereview_reason="finding_batch",
        finding_batch_id="BATCH-1",
        last_finding_batch_generation=1,
    )


def test_locked_candidate_must_be_clean() -> None:
    _assert_blocked("CANDIDATE_NOT_CLEAN", candidate_clean=False)


def test_blocked_review_cli_returns_nonzero(tmp_path: Path) -> None:
    evidence = _evidence(reviewer_status="TIMEOUT", review_verdict=None)
    path = tmp_path / "review.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/ade_os.py"),
            "--root",
            str(ROOT),
            "checkpoint",
            "review",
            "--evidence",
            str(path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 4
    assert json.loads(result.stdout)["status"] == "BLOCKED"


@pytest.mark.parametrize("action", ["review", "close"])
def test_checkpoint_gate_requires_repository_root(action: str) -> None:
    result = core.checkpoint_gate(_evidence(), action)
    assert result["status"] == "BLOCKED"
    assert result["code"] == "REPOSITORY_VALIDATION_REQUIRED"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _locked_git_repo(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review@example.invalid")
    _git(repo, "config", "user.name", "Review Test")
    (repo / "state.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "state.txt")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "state.txt").write_text("candidate\n", encoding="utf-8")
    _git(repo, "add", "state.txt")
    _git(repo, "commit", "-m", "candidate")
    candidate = _git(repo, "rev-parse", "HEAD")

    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "--binary", "--full-index", f"{base}..{candidate}"],
        capture_output=True,
        check=True,
    ).stdout
    diff_hash = hashlib.sha256(diff).hexdigest()
    payload = _review(
        base_sha=base,
        candidate_sha=candidate,
        reviewed_sha=candidate,
        merge_sha=candidate,
        locked_diff_sha256=diff_hash,
        reviewed_diff_sha256=diff_hash,
        merge_diff_sha256=diff_hash,
    )
    return repo, payload


def test_repository_lock_verification_accepts_exact_clean_candidate(tmp_path: Path) -> None:
    repo, payload = _locked_git_repo(tmp_path)
    result = core.validate_closure_repository(repo, payload, action="review")
    assert result["status"] == "PASS"


def test_repository_lock_verification_blocks_dirty_source(tmp_path: Path) -> None:
    repo, payload = _locked_git_repo(tmp_path)
    (repo / "state.txt").write_text("mutated after review\n", encoding="utf-8")
    result = core.validate_closure_repository(repo, payload, action="review")
    assert result["status"] == "BLOCKED"
    assert result["code"] == "CANDIDATE_WORKTREE_DIRTY"


def test_repository_lock_verification_blocks_new_commit_after_review(tmp_path: Path) -> None:
    repo, payload = _locked_git_repo(tmp_path)
    (repo / "extra.txt").write_text("new candidate\n", encoding="utf-8")
    _git(repo, "add", "extra.txt")
    _git(repo, "commit", "-m", "candidate changed")
    result = core.validate_closure_repository(repo, payload, action="review")
    assert result["status"] == "BLOCKED"
    assert result["code"] == "REVIEW_CANDIDATE_STALE"


def test_repository_lock_verification_blocks_forged_diff_hash(tmp_path: Path) -> None:
    repo, payload = _locked_git_repo(tmp_path)
    payload["locked_diff_sha256"] = DIFF_B
    payload["reviewed_diff_sha256"] = DIFF_B
    result = core.validate_closure_repository(repo, payload, action="review")
    assert result["status"] == "BLOCKED"
    assert result["code"] == "LOCKED_DIFF_HASH_MISMATCH"


@pytest.mark.parametrize("severity", ["p0", "p1", "p2"])
def test_any_formal_severity_blocks_pass_verdict(severity: str) -> None:
    _assert_blocked("FINAL_REVIEW_FINDINGS_OPEN", **{severity: 1})


def test_tool_failure_retry_does_not_consume_semantic_review_budget() -> None:
    result = _close(tool_failures=4, final_review_count=1)
    assert result["status"] == "PASS"


def test_malformed_locked_hash_fails_closed() -> None:
    _assert_blocked("CLOSURE_REVIEW_PROTOCOL_INVALID", locked_diff_sha256="bad")


def test_runtime_e2e_claim_without_deploy_is_inconsistent() -> None:
    _assert_blocked(
        "RUNTIME_E2E_EVIDENCE_INCONSISTENT",
        runtime_mode="SOURCE_ONLY",
        deployed=False,
        runtime_e2e=True,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("deployed", 1), ("deployed", "true"), ("runtime_e2e", 1), ("runtime_e2e", "true")],
)
def test_runtime_truth_flags_must_be_boolean(field: str, value: object) -> None:
    _assert_blocked("CLOSURE_REVIEW_PROTOCOL_INVALID", **{field: value})


def test_source_only_claimed_deploy_requires_runtime_e2e_truth() -> None:
    _assert_blocked(
        "RUNTIME_E2E_REQUIRED",
        runtime_mode="SOURCE_ONLY",
        deployed=True,
        runtime_e2e=False,
    )


def test_runtime_required_final_review_can_run_before_deploy() -> None:
    result = core.validate_closure_review_protocol(
        _review(runtime_mode="RUNTIME_REQUIRED", deployed=False, runtime_e2e=False),
        action="review",
    )
    assert result["status"] == "PASS"


def test_reviewer_independence_is_required() -> None:
    _assert_blocked("FINAL_REVIEW_NOT_INDEPENDENT", reviewer_independent=False)


def test_missing_reviewer_independence_is_blocked() -> None:
    payload = _review()
    payload.pop("reviewer_independent")
    result = core.validate_closure_review_protocol(payload, action="review")
    assert result["status"] == "BLOCKED"
    assert result["code"] == "FINAL_REVIEW_NOT_INDEPENDENT"


@pytest.mark.parametrize("batch_id", [True, 1, " ", [], {}])
def test_finding_batch_id_must_be_nonempty_string(batch_id: object) -> None:
    _assert_blocked(
        "CLOSURE_REVIEW_PROTOCOL_INVALID",
        final_review_count=2,
        rereview_reason="finding_batch",
        finding_batch_id=batch_id,
        last_finding_batch_generation=1,
    )


def test_protocol_version_boolean_is_rejected() -> None:
    _assert_blocked("CLOSURE_REVIEW_PROTOCOL_INVALID", protocol_version=True)


def test_last_finding_batch_generation_boolean_is_rejected() -> None:
    _assert_blocked(
        "CLOSURE_REVIEW_PROTOCOL_INVALID",
        final_review_count=2,
        rereview_reason="finding_batch",
        finding_batch_id="RECOVERY-FINDING-BATCH-1",
        last_finding_batch_generation=True,
    )


def test_runtime_required_boolean_only_claim_cannot_close() -> None:
    result = _close(
        runtime_mode="RUNTIME_REQUIRED",
        deployed=True,
        runtime_e2e=True,
    )
    assert result["status"] == "BLOCKED"
    assert result["code"] == "RUNTIME_CLOSURE_EVIDENCE_REQUIRED"


def _runtime_evidence(**overrides: object) -> dict[str, object]:
    evidence: dict[str, object] = {
        "release_sha": SHA_A,
        "local_core": {"health_http_status": 200, "ready_http_status": 200, "db_quick_check": "ok"},
        "consumer_path": {
            "openclaw_healthy": True,
            "configured_base_url": "http://host.docker.internal:8791",
            "tested_base_url": "http://host.docker.internal:8791",
            "reachability_http_status": 200,
            "authenticated_prepare_http_status": 200,
            "authenticated": True,
        },
        "telegram_e2e": {
            "channel_connected": True,
            "fresh": True,
            "observed_at": "2026-09-03T00:45:00+07:00",
            "release_sha": SHA_A,
            "inbound_source": "TELEGRAM_USER",
            "inbound_message_id": 5108,
            "core_prepare_success": True,
            "model_response": True,
            "outbound_success": True,
            "outbound_message_id": 5109,
        },
        "post_test_logs": {"prepare_timeout_count": 0, "prepare_failure_count": 0},
        "rollback": {"release_sha": "b" * 40, "path": "/releases/last-known-good"},
    }
    evidence.update(overrides)
    return evidence


def test_runtime_required_rejects_local_only_runtime_evidence() -> None:
    result = _close(
        runtime_mode="RUNTIME_REQUIRED",
        deployed=True,
        runtime_e2e=True,
        runtime_evidence={
            "release_sha": SHA_A,
            "local_core": {
                "health_http_status": 200,
                "ready_http_status": 200,
                "db_quick_check": "ok",
            },
        },
    )
    assert result["status"] == "BLOCKED"
    assert result["code"] == "RUNTIME_CONSUMER_PATH_REQUIRED"


def test_runtime_consumer_path_must_use_configured_base_url() -> None:
    evidence = _runtime_evidence()
    consumer = evidence["consumer_path"]
    assert isinstance(consumer, dict)
    consumer["tested_base_url"] = "http://host.docker.internal:8790"
    _assert_blocked(
        "RUNTIME_CONSUMER_PATH_MISMATCH",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )


def test_runtime_consumer_path_requires_authenticated_prepare_200() -> None:
    evidence = _runtime_evidence()
    consumer = evidence["consumer_path"]
    assert isinstance(consumer, dict)
    consumer["authenticated_prepare_http_status"] = 401
    _assert_blocked(
        "RUNTIME_CONSUMER_PATH_FAILED",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )


def test_synthetic_request_cannot_substitute_real_telegram_e2e() -> None:
    evidence = _runtime_evidence()
    telegram = evidence["telegram_e2e"]
    assert isinstance(telegram, dict)
    telegram["inbound_source"] = "SYNTHETIC"
    _assert_blocked(
        "TELEGRAM_E2E_REQUIRED",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )


def test_runtime_e2e_requires_model_and_outbound_success() -> None:
    evidence = _runtime_evidence()
    telegram = evidence["telegram_e2e"]
    assert isinstance(telegram, dict)
    telegram["model_response"] = False
    _assert_blocked(
        "TELEGRAM_E2E_REQUIRED",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )


def test_runtime_post_test_logs_must_be_clean() -> None:
    evidence = _runtime_evidence(
        post_test_logs={"prepare_timeout_count": 0, "prepare_failure_count": 1}
    )
    _assert_blocked(
        "RUNTIME_LOGS_NOT_CLEAN",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )


def test_runtime_evidence_must_match_merged_release() -> None:
    evidence = _runtime_evidence(release_sha=SHA_B)
    _assert_blocked(
        "RUNTIME_RELEASE_MISMATCH",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )


def test_complete_structured_runtime_evidence_passes() -> None:
    result = _close(
        runtime_mode="RUNTIME_REQUIRED",
        deployed=True,
        runtime_e2e=True,
        runtime_evidence=_runtime_evidence(),
    )
    assert result["status"] == "PASS"


def test_runtime_local_core_must_have_health_ready_and_db() -> None:
    evidence = _runtime_evidence(
        local_core={
            "health_http_status": 200,
            "ready_http_status": 503,
            "db_quick_check": "ok",
        }
    )
    _assert_blocked(
        "LOCAL_CORE_RUNTIME_REQUIRED",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )


def test_runtime_consumer_prepare_must_be_explicitly_authenticated() -> None:
    evidence = _runtime_evidence()
    consumer = evidence["consumer_path"]
    assert isinstance(consumer, dict)
    consumer["authenticated"] = False
    _assert_blocked(
        "RUNTIME_CONSUMER_PATH_FAILED",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )


def test_runtime_rollback_path_is_required() -> None:
    evidence = _runtime_evidence(rollback={"release_sha": "b" * 40, "path": ""})
    _assert_blocked(
        "ROLLBACK_PATH_REQUIRED",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )


def test_deployed_source_only_checkpoint_still_requires_structured_runtime_evidence() -> None:
    _assert_blocked(
        "RUNTIME_CLOSURE_EVIDENCE_REQUIRED",
        runtime_mode="SOURCE_ONLY", deployed=True, runtime_e2e=True,
    )


def test_telegram_e2e_must_be_bound_to_release_and_real_inbound_message() -> None:
    evidence = _runtime_evidence()
    telegram = evidence["telegram_e2e"]
    assert isinstance(telegram, dict)
    telegram["release_sha"] = SHA_B
    _assert_blocked(
        "TELEGRAM_E2E_REQUIRED",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )
    telegram["release_sha"] = SHA_A
    telegram["inbound_message_id"] = None
    _assert_blocked(
        "TELEGRAM_E2E_REQUIRED",
        runtime_mode="RUNTIME_REQUIRED", deployed=True, runtime_e2e=True, runtime_evidence=evidence,
    )
