from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "coding_preflight.sh"
CONTROLLER_SOURCE = ROOT / "scripts" / "agent" / "coding_preflight_controller.c"


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def parse_output(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def run_guard(
    cwd: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    fault_path = merged_env.pop("_CODING_PREFLIGHT_TEST_FAULT_PATH", None)

    def invoke(guard: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(guard), *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=merged_env,
            check=False,
        )

    if fault_path is None:
        return invoke(GUARD)

    with tempfile.TemporaryDirectory(prefix="coding-preflight-fault-") as temp_dir:
        fault_guard = Path(temp_dir) / "coding_preflight.sh"
        source = GUARD.read_text(encoding="utf-8")
        trusted_path = 'PATH="/usr/bin:/bin"\nexport PATH'
        assert source.count(trusted_path) == 1
        source = source.replace(
            trusted_path,
            'PATH="${CODING_PREFLIGHT_TEST_FAULT_PATH}"\nexport PATH',
            1,
        )
        fault_guard.write_text(source, encoding="utf-8")
        fault_guard.chmod(0o755)
        merged_env["CODING_PREFLIGHT_TEST_FAULT_PATH"] = fault_path
        return invoke(fault_guard)


def build_controller(tmp_path: Path, trusted_guard: Path | None = GUARD) -> Path:
    """Build the loader-safe controller from the repository source under test."""
    controller = tmp_path / "coding-preflight-controller"
    command = ["gcc", "-static", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror"]
    if trusted_guard is not None:
        command.extend(
            [f'-DTRUSTED_GUARD_PATH="{trusted_guard}"', '-DTRUSTED_GUARD_REQUIRE_ROOT=0']
        )
    command.extend(["-o", str(controller), str(CONTROLLER_SOURCE)])
    subprocess.run(command, check=True, capture_output=True, text=True)
    return controller


def controller_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("LD_", "GIT_")) and key not in {"BASH_ENV", "ENV"}
    }


def run_controller(
    controller: Path,
    cwd: Path,
    workspace: Path,
    *git_args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = controller_env()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [
            str(controller),
            "--expected-workspace",
            str(workspace),
            "--",
            "git",
            *git_args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )
def setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    primary = tmp_path / "primary"
    worktree = tmp_path / "feature-wt"
    git(tmp_path, "init", "--bare", str(remote))
    git(tmp_path, "clone", str(remote), str(primary))
    git(primary, "config", "user.name", "Preflight Test")
    git(primary, "config", "user.email", "preflight@example.invalid")
    (primary / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(primary, "add", "tracked.txt")
    git(primary, "commit", "-m", "initial")
    git(primary, "branch", "-M", "main")
    git(primary, "push", "-u", "origin", "main")
    git(primary, "worktree", "add", str(worktree), "-b", "feature")
    git(worktree, "push", "-u", "origin", "feature")
    return primary, worktree


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, Path]:
    return setup_repo(tmp_path)


def coding_args(
    worktree: Path, *, expected_push_url: str | None = None
) -> list[str]:
    if expected_push_url is None:
        expected_push_url = git(worktree, "remote", "get-url", "origin").stdout.strip()
    return [
        "--expected-workspace", str(worktree),
        "--require-isolation", "--require-clean", "--require-upstream",
        "--expected-upstream", "origin/feature",
        "--expected-push-remote", "origin",
        "--expected-push-url", expected_push_url,
        "--expected-git-name", "Preflight Test",
        "--expected-git-email", "preflight@example.invalid",
    ]


def assert_blocked(result: subprocess.CompletedProcess[str], code: str) -> dict[str, str]:
    assert result.returncode != 0, result.stdout + result.stderr
    data = parse_output(result)
    assert data["PREFLIGHT"] == "BLOCKED"
    assert code in data["REASONS"].split(",")
    return data


def test_passes_for_clean_isolated_worktree_with_valid_upstream(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    result = run_guard(worktree, *coding_args(worktree))
    assert result.returncode == 0, result.stdout + result.stderr
    data = parse_output(result)
    assert data["PREFLIGHT"] == "PASS"
    assert data["WORKSPACE"] == str(worktree.resolve())
    assert data["BRANCH"] == "feature"
    assert data["UPSTREAM"] == "origin/feature"
    assert data["DIRTY_TRACKED"] == "0"
    assert data["DIRTY_UNTRACKED"] == "0"
    assert data["UNMERGED"] == "0"
    assert data["WORKTREE_REGISTERED"] == "1"
    assert data["WORKTREE_PRUNABLE"] == "0"


def test_blocks_expected_workspace_mismatch(repo: tuple[Path, Path]) -> None:
    primary, worktree = repo
    args = coding_args(worktree)
    args[1] = str(primary)
    result = run_guard(worktree, *args)
    assert_blocked(result, "WORKSPACE_MISMATCH")


def test_blocks_primary_main_when_isolation_required(repo: tuple[Path, Path]) -> None:
    primary, _ = repo
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--require-isolation",
        "--require-clean",
        "--require-upstream",
        "--expected-upstream",
        "origin/main",
        "--expected-push-remote",
        "origin",
    )
    data = assert_blocked(result, "NOT_ISOLATED_WORKTREE")
    assert "MAIN_NOT_ISOLATED" in data["REASONS"].split(",")


def test_blocks_missing_upstream(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "branch", "--unset-upstream")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "MISSING_OR_INVALID_UPSTREAM")


def test_passes_with_stably_absent_upstream_when_not_required(
    repo: tuple[Path, Path]
) -> None:
    _, worktree = repo
    git(worktree, "branch", "--unset-upstream")
    result = run_guard(worktree, "--expected-workspace", str(worktree))
    assert result.returncode == 0, result.stdout + result.stderr
    assert parse_output(result)["UPSTREAM"] == "NONE"


def test_blocks_detached_head_by_default(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "checkout", "--detach")
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--require-isolation",
        "--require-clean",
    )
    assert_blocked(result, "DETACHED_HEAD")


def test_blocks_dirty_tracked_state(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    (worktree / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "DIRTY_TRACKED")


def test_blocks_unexpected_untracked_state(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    (worktree / "unexpected.txt").write_text("new\n", encoding="utf-8")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "DIRTY_UNTRACKED")


def test_blocks_unmerged_conflict(repo: tuple[Path, Path]) -> None:
    primary, worktree = repo
    git(primary, "checkout", "-b", "conflict")
    (primary / "tracked.txt").write_text("theirs\n", encoding="utf-8")
    git(primary, "add", "tracked.txt")
    git(primary, "commit", "-m", "conflict side")
    (worktree / "tracked.txt").write_text("ours\n", encoding="utf-8")
    git(worktree, "add", "tracked.txt")
    git(worktree, "commit", "-m", "feature side")
    merge = git(worktree, "merge", "conflict", check=False)
    assert merge.returncode != 0
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "UNMERGED_FILES")


def test_blocks_wrong_push_remote(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    args = coding_args(worktree)
    remote_index = args.index("--expected-push-remote") + 1
    args[remote_index] = "not-origin"
    result = run_guard(worktree, *args)
    assert_blocked(result, "PUSH_REMOTE_MISMATCH")


def test_blocks_branch_checked_out_elsewhere(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = repo
    duplicate = tmp_path / "duplicate-feature"
    added = git(
        primary,
        "worktree",
        "add",
        "--force",
        "--force",
        str(duplicate),
        "feature",
        check=False,
    )
    if added.returncode != 0:
        pytest.skip("installed Git does not permit duplicate branch worktrees")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "BRANCH_CHECKED_OUT_ELSEWHERE")


def test_blocks_prunable_cleanup_target(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, _ = repo
    stale = tmp_path / "stale-wt"
    git(primary, "worktree", "add", str(stale), "-b", "stale")
    shutil.rmtree(stale)
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(stale),
        "--destructive-cleanup",
    )
    assert_blocked(result, "WORKTREE_PRUNABLE")


def test_blocks_cleanup_target_with_live_proc_cwd(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, _ = repo
    target = tmp_path / "cleanup-wt"
    git(primary, "worktree", "add", str(target), "-b", "cleanup")
    fake_proc = tmp_path / "proc"
    pid_dir = fake_proc / "1234"
    pid_dir.mkdir(parents=True)
    (pid_dir / "status").write_text(
        f"Name:\ttest\nUid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n",
        encoding="utf-8",
    )
    (pid_dir / "cwd").symlink_to(target, target_is_directory=True)
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        },
    )
    assert_blocked(result, "LIVE_PROCESS_PRESENT")


def test_blocks_destructive_cleanup_without_recovery_evidence(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, _ = repo
    target = tmp_path / "archive-wt"
    git(primary, "worktree", "add", str(target), "-b", "archive-target")
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
    )
    data = assert_blocked(result, "ARCHIVE_HEAD_OR_BUNDLE_MISSING")
    reasons = data["REASONS"].split(",")
    assert "CHECKSUM_EVIDENCE_MISSING" in reasons
    assert "COVERAGE_EVIDENCE_MISSING" in reasons
    assert data["ARCHIVE_REQUIREMENT_STATE"] == "MISSING"


def test_agents_requires_coding_preflight_guard() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "scripts/coding_preflight.sh" in agents
    assert "/usr/local/libexec/anh-duong/coding-preflight-controller" in agents
    assert "run `scripts/coding_preflight.sh`" not in agents
    assert "non-zero" in agents
    assert "BLOCKED" in agents


def test_blocks_archive_ref_that_does_not_match_cleanup_head(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, _ = repo
    target = tmp_path / "mismatch-archive-wt"
    git(primary, "worktree", "add", str(target), "-b", "mismatch-archive")
    (target / "tracked.txt").write_text("new head\n", encoding="utf-8")
    git(target, "add", "tracked.txt")
    git(target, "commit", "-m", "advance cleanup target")
    checksum = tmp_path / "checksums.txt"
    coverage = tmp_path / "coverage.txt"
    checksum.write_text("sha256 evidence\n", encoding="utf-8")
    coverage.write_text("coverage evidence\n", encoding="utf-8")
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        "refs/heads/main",
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
    )
    assert_blocked(result, "ARCHIVE_HEAD_MISMATCH")


def coverage_encode(value: str) -> str:
    out: list[str] = []
    for byte in value.encode():
        if byte in (37, 61) or byte < 32 or byte >= 127:
            out.append(f"%{byte:02X}")
        else:
            out.append(chr(byte))
    return "".join(out)


def write_recovery_evidence(
    primary: Path, target: Path, tmp_path: Path
) -> tuple[str, Path, Path, Path | None, Path | None]:
    head = git(target, "rev-parse", "HEAD").stdout.strip()
    stem = hashlib.sha256(str(target).encode()).hexdigest()[:12]
    ref = f"refs/archive/test/{hashlib.sha256(str(target).encode()).hexdigest()[:16]}"
    git(primary, "update-ref", ref, head)
    status = git(target, "status", "--porcelain=v1", "-uall").stdout.splitlines()
    tracked_count = sum(not line.startswith("??") for line in status)
    untracked_count = sum(line.startswith("??") for line in status)
    patch: Path | None = None
    archive: Path | None = None
    if tracked_count:
        patch = tmp_path / f"recovery-{stem}.patch"
        patch.write_text(git(target, "diff", "--binary", "HEAD").stdout, encoding="utf-8")
    untracked_cp = subprocess.run(
        ["git", "ls-files", "-o", "--exclude-standard", "-z"],
        cwd=target, capture_output=True, check=True,
    )
    untracked = [os.fsdecode(item) for item in untracked_cp.stdout.split(b"\0") if item]
    if untracked:
        archive = tmp_path / f"recovery-{stem}.tar.gz"
        subprocess.run(
            ["tar", "-C", str(target), "-czf", str(archive), *untracked],
            check=True,
            capture_output=True,
            text=True,
        )
    coverage = tmp_path / f"recovery-{stem}.coverage"
    coverage.write_text(
        "\n".join(
            [
                f"TARGET_HEAD={head}",
                f"TARGET_PATH={coverage_encode(str(target.resolve()))}",
                f"DIRTY_TRACKED={tracked_count}",
                f"DIRTY_UNTRACKED={untracked_count}",
                f"ARCHIVE_REF={coverage_encode(ref)}",
                "COVERAGE_BAD=0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    checksum = tmp_path / f"recovery-{stem}.sha256"
    checked = [coverage]
    if patch is not None:
        checked.append(patch)
    if archive is not None:
        checked.append(archive)
    checksum_lines = []
    for path in checked:
        result = subprocess.run(
            ["sha256sum", str(path)], capture_output=True, text=True, check=True
        )
        checksum_lines.append(result.stdout)
    checksum.write_text("".join(checksum_lines), encoding="utf-8")
    return ref, checksum, coverage, patch, archive


def test_blocks_spoofed_recovery_evidence(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, _ = repo
    target = tmp_path / "spoof-wt"
    git(primary, "worktree", "add", str(target), "-b", "spoof")
    (target / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (target / "new.txt").write_text("new\n", encoding="utf-8")
    fake = ROOT / "AGENTS.md"
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        "HEAD",
        "--tracked-patch",
        str(fake),
        "--untracked-archive",
        str(fake),
        "--checksum-evidence",
        str(fake),
        "--coverage-evidence",
        str(fake),
    )
    assert_blocked(result, "ARCHIVE_REF_NOT_DURABLE")


def test_blocks_proc_root_override_outside_test_mode(repo: tuple[Path, Path]) -> None:
    primary, _ = repo
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(primary),
        env={"CODING_PREFLIGHT_PROC_ROOT": "/definitely/not/proc"},
    )
    assert_blocked(result, "PROC_ROOT_OVERRIDE_FORBIDDEN")


def test_blocks_invalid_proc_root_in_test_mode(repo: tuple[Path, Path]) -> None:
    primary, _ = repo
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(primary),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": "/definitely/not/proc",
        },
    )
    assert_blocked(result, "PROC_ROOT_INVALID")


def test_blocks_target_status_failure(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, _ = repo
    target = tmp_path / "status-fail-wt"
    git(primary, "worktree", "add", str(target), "-b", "status-fail")
    index_raw = git(target, "rev-parse", "--git-path", "index").stdout.strip()
    index_path = Path(index_raw)
    if not index_path.is_absolute():
        index_path = target / index_path
    index_path.unlink()
    index_path.mkdir()
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
    )
    assert_blocked(result, "TARGET_STATUS_UNAVAILABLE")


def test_uses_git_push_semantics_for_custom_refspec(repo: tuple[Path, Path]) -> None:
    primary, worktree = repo
    git(worktree, "config", "remote.origin.push", "refs/heads/feature:refs/heads/review")
    result = run_guard(
        worktree,
        *coding_args(worktree),
        "--expected-push-target",
        "origin:refs/heads/review",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert parse_output(result)["PUSH_TARGET"] == "origin:refs/heads/review"


def test_blocks_branch_behind_upstream(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = repo
    remote = git(primary, "remote", "get-url", "origin").stdout.strip()
    peer = tmp_path / "peer"
    git(tmp_path, "clone", remote, str(peer))
    git(peer, "config", "user.name", "Peer")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "feature")
    (peer / "peer.txt").write_text("remote advance\n", encoding="utf-8")
    git(peer, "add", "peer.txt")
    git(peer, "commit", "-m", "advance remote feature")
    git(peer, "push", "origin", "feature")
    git(worktree, "fetch", "origin")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "UPSTREAM_BEHIND")


def test_preserves_index_metadata_when_clean(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    index_raw = git(worktree, "rev-parse", "--git-path", "index").stdout.strip()
    index_path = Path(index_raw)
    if not index_path.is_absolute():
        index_path = worktree / index_path
    tracked = worktree / "tracked.txt"
    tracked_stat = tracked.stat()
    os.utime(
        tracked,
        ns=(tracked_stat.st_atime_ns, index_path.stat().st_mtime_ns + 2_000_000_000),
    )
    before_mtime = index_path.stat().st_mtime_ns
    before_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
    result = run_guard(worktree, *coding_args(worktree))
    after_mtime = index_path.stat().st_mtime_ns
    after_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
    assert result.returncode == 0, result.stdout + result.stderr
    assert after_mtime == before_mtime
    assert after_hash == before_hash


def test_machine_output_escapes_newlines(repo: tuple[Path, Path]) -> None:
    primary, _ = repo
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--invalid\nPREFLIGHT=PASS",
    )
    data = assert_blocked(result, "INVALID_INVOCATION")
    assert result.stdout.count("PREFLIGHT=") == 1
    assert data["PREFLIGHT"] == "BLOCKED"
    assert "%0A" in data["INVALID_DETAIL"]


def test_expected_workspace_symlink_resolves_to_same_realpath(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    link = tmp_path / "worktree-link"
    link.symlink_to(worktree, target_is_directory=True)
    args = coding_args(worktree)
    args[1] = str(link)
    result = run_guard(worktree, *args)
    assert result.returncode == 0, result.stdout + result.stderr


def test_valid_recovery_evidence_passes(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, _ = repo
    target = tmp_path / "valid-recovery-wt"
    git(primary, "worktree", "add", str(target), "-b", "valid-recovery")
    (target / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    (target / "new.txt").write_text("new\n", encoding="utf-8")
    ref, checksum, coverage, patch, archive = write_recovery_evidence(primary, target, tmp_path)
    assert patch is not None and archive is not None
    fake_proc = tmp_path / "proc"
    fake_proc.mkdir()
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--tracked-patch",
        str(patch),
        "--untracked-archive",
        str(archive),
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        },
    )
    data = assert_blocked(result, "TEST_PROC_OVERRIDE_NON_AUTHORIZING")
    assert data["ARCHIVE_REQUIREMENT_STATE"] == "PASS"


def test_blocks_stale_tracked_patch(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, _ = repo
    target = tmp_path / "stale-patch-wt"
    git(primary, "worktree", "add", str(target), "-b", "stale-patch")
    (target / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    ref, checksum, coverage, patch, _ = write_recovery_evidence(primary, target, tmp_path)
    assert patch is not None
    patch.write_text("not the current diff\n", encoding="utf-8")
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--tracked-patch",
        str(patch),
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
    )
    assert_blocked(result, "TRACKED_PATCH_MISMATCH")


def test_blocks_stale_untracked_archive(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, _ = repo
    target = tmp_path / "stale-archive-wt"
    git(primary, "worktree", "add", str(target), "-b", "stale-archive")
    (target / "new.txt").write_text("before\n", encoding="utf-8")
    ref, checksum, coverage, _, archive = write_recovery_evidence(primary, target, tmp_path)
    assert archive is not None
    (target / "new.txt").write_text("after\n", encoding="utf-8")
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--untracked-archive",
        str(archive),
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
    )
    assert_blocked(result, "UNTRACKED_ARCHIVE_MISMATCH")


def test_blocks_coverage_not_bound_to_target(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, _ = repo
    target = tmp_path / "coverage-wt"
    git(primary, "worktree", "add", str(target), "-b", "coverage")
    ref, checksum, coverage, _, _ = write_recovery_evidence(primary, target, tmp_path)
    coverage.write_text("TARGET_HEAD=wrong\nCOVERAGE_BAD=0\n", encoding="utf-8")
    coverage_sha = subprocess.run(
        ["sha256sum", str(coverage)], capture_output=True, text=True, check=True
    ).stdout
    checksum.write_text(coverage_sha, encoding="utf-8")
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
    )
    assert_blocked(result, "COVERAGE_EVIDENCE_INVALID")


def test_blocks_diverged_upstream(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = repo
    remote = git(primary, "remote", "get-url", "origin").stdout.strip()
    (worktree / "local.txt").write_text("local advance\n", encoding="utf-8")
    git(worktree, "add", "local.txt")
    git(worktree, "commit", "-m", "local advance")
    peer = tmp_path / "diverged-peer"
    git(tmp_path, "clone", remote, str(peer))
    git(peer, "config", "user.name", "Peer")
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "checkout", "feature")
    (peer / "remote.txt").write_text("remote advance\n", encoding="utf-8")
    git(peer, "add", "remote.txt")
    git(peer, "commit", "-m", "remote advance")
    git(peer, "push", "origin", "feature")
    git(worktree, "fetch", "origin")
    result = run_guard(worktree, *coding_args(worktree))
    data = assert_blocked(result, "UPSTREAM_DIVERGED")
    assert "UPSTREAM_BEHIND" in data["REASONS"].split(",")
    assert data["DIVERGENCE_AHEAD"] == "1"
    assert data["DIVERGENCE_BEHIND"] == "1"


def git_wrapper_env(tmp_path: Path, body: str, **extra: str) -> dict[str, str]:
    real_git = shutil.which("git")
    assert real_git is not None
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    wrapper = bin_dir / "git"
    wrapper.write_text(
        "#!/usr/bin/env bash\nset -u\nREAL_GIT="
        + repr(real_git)
        + "\n"
        + body
        + '\nexec "$REAL_GIT" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    fault_path = f"{bin_dir}:{os.environ['PATH']}"
    return {"PATH": fault_path, "_CODING_PREFLIGHT_TEST_FAULT_PATH": fault_path, **extra}


def test_proc_fixture_override_is_never_authorizing(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "override-target"
    git(primary, "worktree", "add", str(target), "-b", "override-target")
    fake_proc = tmp_path / "proc"
    fake_proc.mkdir()
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        },
    )
    assert_blocked(result, "TEST_PROC_OVERRIDE_NON_AUTHORIZING")


def test_cross_uid_proc_cwd_blocks_cleanup(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = repo
    target = tmp_path / "cross-uid-target"
    git(primary, "worktree", "add", str(target), "-b", "cross-uid-target")
    fake_proc = tmp_path / "proc-cross-uid"
    pid_dir = fake_proc / "4242"
    pid_dir.mkdir(parents=True)
    other_uid = os.getuid() + 1
    (pid_dir / "status").write_text(
        f"Name:\ttest\nUid:\t{other_uid}\t{other_uid}\t{other_uid}\t{other_uid}\n",
        encoding="utf-8",
    )
    (pid_dir / "cwd").symlink_to(target, target_is_directory=True)
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        },
    )
    assert_blocked(result, "LIVE_PROCESS_PRESENT")


def test_destructive_cleanup_blocks_primary_worktree(repo: tuple[Path, Path]) -> None:
    primary, _ = repo
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--cleanup-target",
        str(primary),
        "--destructive-cleanup",
    )
    assert_blocked(result, "PRIMARY_WORKTREE_CLEANUP_FORBIDDEN")


def test_blocks_multiple_configured_push_targets(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "--unset-all", "remote.origin.push", check=False)
    git(worktree, "config", "--add", "remote.origin.push", "refs/heads/feature:refs/heads/review")
    git(worktree, "config", "--add", "remote.origin.push", "refs/heads/feature:refs/heads/backup")
    result = run_guard(
        worktree,
        *coding_args(worktree),
        "--expected-push-target",
        "origin:refs/heads/review",
    )
    assert_blocked(result, "MULTIPLE_PUSH_TARGETS")


def test_blocks_failed_unmerged_probe(repo: tuple[Path, Path], tmp_path: Path) -> None:
    _, worktree = repo
    env = git_wrapper_env(
        tmp_path,
        'if [[ "$1" == "ls-files" && "$2" == "--unmerged" ]]; then exit 73; fi',
    )
    result = run_guard(worktree, *coding_args(worktree), env=env)
    assert_blocked(result, "UNMERGED_PROBE_FAILED")


def test_blocks_failed_worktree_probe(repo: tuple[Path, Path], tmp_path: Path) -> None:
    _, worktree = repo
    env = git_wrapper_env(
        tmp_path,
        'if [[ "$1" == "worktree" && "$2" == "list" ]]; then exit 74; fi',
    )
    result = run_guard(worktree, *coding_args(worktree), env=env)
    assert_blocked(result, "WORKTREE_PROBE_FAILED")


def sha_mutation_env(tmp_path: Path, target: Path, action: str) -> dict[str, str]:
    real_sha = shutil.which("sha256sum")
    assert real_sha is not None
    bin_dir = tmp_path / "sha-bin"
    bin_dir.mkdir(exist_ok=True)
    marker = tmp_path / "sha-mutated"
    wrapper = bin_dir / "sha256sum"
    wrapper.write_text(
        "#!/usr/bin/env bash\nset -u\n"
        f"REAL_SHA={real_sha!r}\nMARKER={str(marker)!r}\nTARGET={str(target)!r}\n"
        'if [[ "${1:-}" == "-c" && ! -e "$MARKER" ]]; then\n'
        '  "$REAL_SHA" "$@"; rc=$?; touch "$MARKER"; '
        + action
        + '; exit $rc\nfi\nexec "$REAL_SHA" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    fault_path = f"{bin_dir}:{os.environ['PATH']}"
    return {"PATH": fault_path, "_CODING_PREFLIGHT_TEST_FAULT_PATH": fault_path}


def test_revalidates_target_state_before_pass(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = repo
    target = tmp_path / "toctou-state-target"
    git(primary, "worktree", "add", str(target), "-b", "toctou-state")
    (target / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    ref, checksum, coverage, patch, _ = write_recovery_evidence(primary, target, tmp_path)
    assert patch is not None
    fake_proc = tmp_path / "proc-toctou-state"
    fake_proc.mkdir()
    env = sha_mutation_env(tmp_path, target, 'printf "late\\n" >> "$TARGET/tracked.txt"')
    env.update(
        {
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        }
    )
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--tracked-patch",
        str(patch),
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
        env=env,
    )
    assert_blocked(result, "TARGET_STATE_CHANGED")


def test_revalidates_live_process_before_pass(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = repo
    target = tmp_path / "toctou-proc-target"
    git(primary, "worktree", "add", str(target), "-b", "toctou-proc")
    ref, checksum, coverage, _, _ = write_recovery_evidence(primary, target, tmp_path)
    fake_proc = tmp_path / "proc-toctou-proc"
    fake_proc.mkdir()
    pid_dir = fake_proc / "7777"
    uid_fields = "\\t".join([str(os.getuid())] * 4)
    status_path = pid_dir / "status"
    action = (
        f"mkdir -p {str(pid_dir)!r}; "
        f'printf "Name:\\ttest\\nUid:\\t{uid_fields}\\n" > {str(status_path)!r}; '
        f"ln -s {str(target)!r} {str(pid_dir / 'cwd')!r}"
    )
    env = sha_mutation_env(tmp_path, target, action)
    env.update(
        {
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        }
    )
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
        env=env,
    )
    assert_blocked(result, "LIVE_PROCESS_PRESENT")


def test_blocks_divergence_probe_failure(repo: tuple[Path, Path], tmp_path: Path) -> None:
    _, worktree = repo
    env = git_wrapper_env(
        tmp_path,
        'if [[ "$1" == "rev-list" ]]; then exit 77; fi',
    )
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--require-isolation",
        "--require-clean",
        env=env,
    )
    assert_blocked(result, "DIVERGENCE_PROBE_FAILED")


def test_blocks_push_ref_probe_failure(repo: tuple[Path, Path], tmp_path: Path) -> None:
    _, worktree = repo
    env = git_wrapper_env(
        tmp_path,
        'if [[ "$1" == "for-each-ref" ]]; then exit 78; fi',
    )
    result = run_guard(worktree, "--expected-workspace", str(worktree), env=env)
    assert_blocked(result, "PUSH_PROBE_FAILED")


def test_blocks_wildcard_push_refspec(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "--unset-all", "remote.origin.push", check=False)
    git(
        worktree,
        "config",
        "--add",
        "remote.origin.push",
        "refs/heads/*:refs/heads/*",
    )
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "MULTIPLE_PUSH_TARGETS")


def test_blocks_push_default_matching(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "--unset-all", "remote.origin.push", check=False)
    git(worktree, "config", "push.default", "matching")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "MULTIPLE_PUSH_TARGETS")


def test_blocks_ignored_content_in_cleanup_target(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "ignored-target"
    git(primary, "worktree", "add", str(target), "-b", "ignored-target")
    (target / ".gitignore").write_text("secret.env\n", encoding="utf-8")
    git(target, "add", ".gitignore")
    git(target, "commit", "-m", "ignore secret")
    (target / "secret.env").write_text("preserve-me\n", encoding="utf-8")
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
    )
    assert_blocked(result, "IGNORED_CONTENT_PRESENT")


def test_machine_output_escapes_terminal_controls(repo: tuple[Path, Path]) -> None:
    primary, _ = repo
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--bad\x1b[31m\x7fvalue",
    )
    data = assert_blocked(result, "INVALID_INVOCATION")
    assert "\x1b" not in result.stdout
    assert "\x7f" not in result.stdout
    assert "%1B" in data["INVALID_DETAIL"]
    assert "%7F" in data["INVALID_DETAIL"]


def test_blocks_non_hostwide_proc_view(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = repo
    target = tmp_path / "proc-view-target"
    git(primary, "worktree", "add", str(target), "-b", "proc-view-target")
    fake_proc = tmp_path / "proc-view"
    (fake_proc / "self").mkdir(parents=True)
    (fake_proc / "self" / "status").write_text(
        "Name:\ttest\nNSpid:\t100\t1\n",
        encoding="utf-8",
    )
    (fake_proc / "mounts").write_text(
        "proc /proc proc rw,hidepid=2 0 0\n",
        encoding="utf-8",
    )
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        },
    )
    assert_blocked(result, "PROC_VIEW_NOT_HOST_WIDE")


def git_second_status_mutation_env(
    tmp_path: Path, target: Path, action: str
) -> dict[str, str]:
    real_git = shutil.which("git")
    assert real_git is not None
    bin_dir = tmp_path / "git-mutate-bin"
    bin_dir.mkdir(exist_ok=True)
    counter = tmp_path / "git-status-count"
    wrapper = bin_dir / "git"
    wrapper.write_text(
        "#!/usr/bin/env bash\nset -u\n"
        f"REAL_GIT={real_git!r}\nTARGET={str(target)!r}\nCOUNTER={str(counter)!r}\n"
        'if [[ "$1" == "-C" && "$2" == "$TARGET" && "$3" == "status" ]]; then\n'
        '  n=0; [[ -f "$COUNTER" ]] && n=$(cat "$COUNTER"); n=$((n+1)); '
        'printf "%s" "$n" > "$COUNTER";\n'
        '  if [[ "$n" -eq 2 ]]; then "$REAL_GIT" "$@"; rc=$?; '
        + action
        + '; exit $rc; fi\nfi\nexec "$REAL_GIT" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    fault_path = f"{bin_dir}:{os.environ['PATH']}"
    return {"PATH": fault_path, "_CODING_PREFLIGHT_TEST_FAULT_PATH": fault_path}


def test_revalidates_recovery_artifacts_before_pass(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "artifact-recheck-target"
    git(primary, "worktree", "add", str(target), "-b", "artifact-recheck")
    ref, checksum, coverage, _, _ = write_recovery_evidence(primary, target, tmp_path)
    fake_proc = tmp_path / "proc-artifact-recheck"
    fake_proc.mkdir()
    action = f'printf "tampered\\n" >> {str(coverage)!r}'
    env = git_second_status_mutation_env(tmp_path, target, action)
    env.update(
        {
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        }
    )
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
        env=env,
    )
    assert_blocked(result, "RECOVERY_EVIDENCE_CHANGED")


def test_revalidates_archive_ref_before_pass(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "ref-recheck-target"
    git(primary, "worktree", "add", str(target), "-b", "ref-recheck")
    ref, checksum, coverage, _, _ = write_recovery_evidence(primary, target, tmp_path)
    (primary / "main-only.txt").write_text("alternate\n", encoding="utf-8")
    git(primary, "add", "main-only.txt")
    git(primary, "commit", "-m", "alternate ref target")
    alternate = git(primary, "rev-parse", "HEAD").stdout.strip()
    fake_proc = tmp_path / "proc-ref-recheck"
    fake_proc.mkdir()
    action = f'git -C {str(primary)!r} update-ref {ref!r} {alternate!r}'
    env = git_second_status_mutation_env(tmp_path, target, action)
    env.update(
        {
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        }
    )
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
        env=env,
    )
    assert_blocked(result, "RECOVERY_REF_CHANGED")


def readlink_disappearing_pid_env(tmp_path: Path, pid_dir: Path) -> dict[str, str]:
    real_readlink = shutil.which("readlink")
    assert real_readlink is not None
    bin_dir = tmp_path / "readlink-bin"
    bin_dir.mkdir(exist_ok=True)
    wrapper = bin_dir / "readlink"
    wrapper.write_text(
        "#!/usr/bin/env bash\nset -u\n"
        f"REAL_READLINK={real_readlink!r}\nPID_DIR={str(pid_dir)!r}\n"
        'if [[ "${1:-}" == "$PID_DIR/cwd" ]]; then '
        'rm -rf "$PID_DIR"; exit 1; fi\n'
        'exec "$REAL_READLINK" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    fault_path = f"{bin_dir}:{os.environ['PATH']}"
    return {"PATH": fault_path, "_CODING_PREFLIGHT_TEST_FAULT_PATH": fault_path}


def test_pid_exit_churn_does_not_report_incomplete(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "pid-churn-target"
    git(primary, "worktree", "add", str(target), "-b", "pid-churn")
    fake_proc = tmp_path / "proc-churn"
    pid_dir = fake_proc / "9999"
    pid_dir.mkdir(parents=True)
    (pid_dir / "status").write_text("Name:\ttest\n", encoding="utf-8")
    (pid_dir / "cwd").symlink_to(target, target_is_directory=True)
    env = readlink_disappearing_pid_env(tmp_path, pid_dir)
    env.update(
        {
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        }
    )
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        env=env,
    )
    data = assert_blocked(result, "TEST_PROC_OVERRIDE_NON_AUTHORIZING")
    reasons = data["REASONS"].split(",")
    assert "PROC_SCAN_INCOMPLETE" not in reasons
    assert "PROC_CWD_UNREADABLE" not in reasons


def test_blocks_dirty_submodule_content(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    subrepo = tmp_path / "subrepo"
    git(tmp_path, "init", str(subrepo))
    git(subrepo, "config", "user.name", "Preflight Test")
    git(subrepo, "config", "user.email", "preflight@example.invalid")
    (subrepo / "sub.txt").write_text("base\n", encoding="utf-8")
    git(subrepo, "add", "sub.txt")
    git(subrepo, "commit", "-m", "sub base")
    target = tmp_path / "submodule-target"
    git(primary, "worktree", "add", str(target), "-b", "submodule-target")
    git(
        target,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(subrepo),
        "vendor/sub",
    )
    git(target, "add", ".gitmodules", "vendor/sub")
    git(target, "commit", "-m", "add submodule")
    (target / "vendor" / "sub" / "sub.txt").write_text("dirty\n", encoding="utf-8")
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
    )
    assert_blocked(result, "DIRTY_SUBMODULE_PRESENT")


def test_blocks_push_config_probe_failure(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    env = git_wrapper_env(
        tmp_path,
        'if [[ "$1" == "config" && " $* " == *" --get-all "* ]]; then exit 79; fi',
    )
    result = run_guard(worktree, *coding_args(worktree), env=env)
    assert_blocked(result, "PUSH_CONFIG_PROBE_FAILED")


def test_blocks_locked_cleanup_target(repo: tuple[Path, Path], tmp_path: Path) -> None:
    primary, worktree = repo
    target = tmp_path / "locked-target"
    git(primary, "worktree", "add", str(target), "-b", "locked-target")
    git(primary, "worktree", "lock", "--reason", "protected fixture", str(target))
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
    )
    assert_blocked(result, "WORKTREE_LOCKED")


def test_blocks_cleanup_target_with_open_fd(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "fd-target"
    git(primary, "worktree", "add", str(target), "-b", "fd-target")
    held = target / "held.txt"
    held.write_text("active\n", encoding="utf-8")
    fake_proc = tmp_path / "proc-fd"
    pid_dir = fake_proc / "4242"
    (pid_dir / "fd").mkdir(parents=True)
    (pid_dir / "status").write_text("Name:\ttest\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (pid_dir / "cwd").symlink_to(outside, target_is_directory=True)
    (pid_dir / "fd" / "7").symlink_to(held)
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        },
    )
    assert_blocked(result, "LIVE_FILE_DESCRIPTOR_PRESENT")


def test_blocks_archive_revision_expression(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "archive-expression-target"
    git(primary, "worktree", "add", str(target), "-b", "archive-expression")
    head = git(target, "rev-parse", "HEAD").stdout.strip()
    ref = "refs/archive/test/archive-expression"
    git(primary, "update-ref", ref, head)
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        f"{ref}^0",
    )
    assert_blocked(result, "ARCHIVE_REF_NOT_EXACT")


def test_blocks_invalid_git_author_identity(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "user.name", "")
    git(worktree, "config", "user.email", "invalid-email")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "GIT_IDENTITY_INVALID")


def test_blocks_cleanup_target_inside_common_git(
    repo: tuple[Path, Path]
) -> None:
    primary, worktree = repo
    common = Path(git(primary, "rev-parse", "--git-common-dir").stdout.strip())
    if not common.is_absolute():
        common = (primary / common).resolve()
    target = common / "nested-cleanup-wt"
    git(primary, "worktree", "add", str(target), "-b", "nested-cleanup")
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
    )
    assert_blocked(result, "CLEANUP_TARGET_INSIDE_COMMON_GIT")


def test_blocks_uninitialized_submodule(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    subrepo = tmp_path / "subrepo-uninit"
    git(tmp_path, "init", str(subrepo))
    git(subrepo, "config", "user.name", "Preflight Test")
    git(subrepo, "config", "user.email", "preflight@example.invalid")
    (subrepo / "sub.txt").write_text("base\n", encoding="utf-8")
    git(subrepo, "add", "sub.txt")
    git(subrepo, "commit", "-m", "sub base")
    target = tmp_path / "uninitialized-submodule-target"
    git(primary, "worktree", "add", str(target), "-b", "uninitialized-submodule")
    git(target, "-c", "protocol.file.allow=always", "submodule", "add", str(subrepo), "vendor/sub")
    git(target, "add", ".gitmodules", "vendor/sub")
    git(target, "commit", "-m", "add submodule")
    git(target, "submodule", "deinit", "-f", "vendor/sub")
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
    )
    assert_blocked(result, "UNINITIALIZED_SUBMODULE_PRESENT")


def test_machine_output_escapes_c1_unicode_control(repo: tuple[Path, Path]) -> None:
    primary, _ = repo
    result = run_guard(
        primary,
        "--expected-workspace",
        str(primary),
        "--bad\u009bvalue",
    )
    data = assert_blocked(result, "INVALID_INVOCATION")
    assert "\u009b" not in result.stdout
    assert "%C2%9B" in data["INVALID_DETAIL"]


def test_worktree_path_with_newline_is_parsed_safely(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, _ = repo
    target = tmp_path / "line\nbreak-wt"
    git(primary, "worktree", "add", str(target), "-b", "newline-path")
    git(target, "push", "-u", "origin", "newline-path")
    result = run_guard(
        target,
        "--expected-workspace",
        str(target),
        "--require-isolation",
        "--require-clean",
        "--require-upstream",
        "--expected-upstream",
        "origin/newline-path",
        "--expected-push-remote",
        "origin",
        "--expected-push-url",
        git(target, "remote", "get-url", "origin").stdout.strip(),
        "--expected-git-name",
        "Preflight Test",
        "--expected-git-email",
        "preflight@example.invalid",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_zombie_without_cwd_is_not_scan_failure(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "zombie-target"
    git(primary, "worktree", "add", str(target), "-b", "zombie-target")
    fake_proc = tmp_path / "proc-zombie"
    (fake_proc / "self").mkdir(parents=True)
    (fake_proc / "self" / "status").write_text("Name:\ttest\nNSpid:\t1\n", encoding="utf-8")
    (fake_proc / "mounts").write_text("proc /proc proc rw 0 0\n", encoding="utf-8")
    pid_dir = fake_proc / "5555"
    pid_dir.mkdir()
    (pid_dir / "status").write_text(
        "Name:\tzombie\nState:\tZ (zombie)\n",
        encoding="utf-8",
    )
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        env={"CODING_PREFLIGHT_TEST_MODE": "1", "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc)},
    )
    data = assert_blocked(result, "TEST_PROC_OVERRIDE_NON_AUTHORIZING")
    assert "PROC_CWD_UNREADABLE" not in data["REASONS"].split(",")


def git_second_worktree_list_failure_env(tmp_path: Path) -> dict[str, str]:
    real_git = shutil.which("git")
    assert real_git is not None
    bin_dir = tmp_path / "worktree-refresh-bin"
    bin_dir.mkdir(exist_ok=True)
    counter = tmp_path / "worktree-list-count"
    wrapper = bin_dir / "git"
    wrapper.write_text(
        "#!/usr/bin/env bash\nset -u\n"
        f"REAL_GIT={real_git!r}\nCOUNTER={str(counter)!r}\n"
        'if [[ "$1" == "worktree" && "$2" == "list" ]]; then\n'
        '  n=0; [[ -f "$COUNTER" ]] && n=$(cat "$COUNTER"); '
        'n=$((n+1)); printf "%s" "$n" > "$COUNTER";\n'
        '  if [[ "$n" -ge 2 ]]; then exit 88; fi\n'
        'fi\nexec "$REAL_GIT" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    fault_path = f"{bin_dir}:{os.environ['PATH']}"
    return {"PATH": fault_path, "_CODING_PREFLIGHT_TEST_FAULT_PATH": fault_path}


def test_destructive_cleanup_revalidates_worktree_registration(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "revalidate-registration-target"
    git(primary, "worktree", "add", str(target), "-b", "revalidate-registration")
    env = git_second_worktree_list_failure_env(tmp_path)
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        env=env,
    )
    assert_blocked(result, "WORKTREE_REVALIDATION_FAILED")


def test_blocks_pid_namespace_local_proc_root(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "pidns-target"
    git(primary, "worktree", "add", str(target), "-b", "pidns-target")
    fake_proc = tmp_path / "proc-pidns"
    (fake_proc / "self").mkdir(parents=True)
    (fake_proc / "1").mkdir()
    (fake_proc / "self" / "status").write_text(
        "Name:\ttest\nNSpid:\t7\n", encoding="utf-8"
    )
    (fake_proc / "1" / "status").write_text(
        "Name:\tbwrap\nNSpid:\t1\n", encoding="utf-8"
    )
    (fake_proc / "1" / "comm").write_text("bwrap\n", encoding="utf-8")
    (fake_proc / "1" / "cgroup").write_text("0::/sandbox\n", encoding="utf-8")
    (fake_proc / "mounts").write_text("proc /proc proc rw 0 0\n", encoding="utf-8")
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        env={"CODING_PREFLIGHT_TEST_MODE": "1", "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc)},
    )
    assert_blocked(result, "PROC_VIEW_NOT_HOST_WIDE")


def test_blocks_systemd_pid_namespace_when_wsl_oracle_differs(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "systemd-pidns-target"
    git(primary, "worktree", "add", str(target), "-b", "systemd-pidns-target")
    fake_proc = tmp_path / "proc-systemd-pidns"
    (fake_proc / "self" / "ns").mkdir(parents=True)
    (fake_proc / "1").mkdir()
    (fake_proc / "self" / "status").write_text("Name:\ttest\nNSpid:\t7\n", encoding="utf-8")
    (fake_proc / "self" / "ns" / "pid").write_text("namespace\n", encoding="utf-8")
    (fake_proc / "1" / "status").write_text("Name:\tsystemd\nNSpid:\t1\n", encoding="utf-8")
    (fake_proc / "1" / "comm").write_text("systemd\n", encoding="utf-8")
    (fake_proc / "1" / "cgroup").write_text("0::/init.scope\n", encoding="utf-8")
    (fake_proc / "mounts").write_text("proc /proc proc rw 0 0\n", encoding="utf-8")
    fake_wsl = tmp_path / "wsl.exe"
    fake_wsl.write_text("#!/usr/bin/env bash\nprintf '4:999999\\n'\n", encoding="utf-8")
    fake_wsl.chmod(0o755)
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
            "CODING_PREFLIGHT_WSL_EXE": str(fake_wsl),
        },
    )
    assert_blocked(result, "PROC_VIEW_NOT_HOST_WIDE")


def test_blocks_dirty_count_parser_failure(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    real_awk = shutil.which("awk")
    assert real_awk is not None
    bin_dir = tmp_path / "awk-fail-bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "awk"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "case \"${1:-}\" in *'substr($0,1,2)'*) exit 81;; esac\n"
        f"exec {real_awk!r} \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    fault_path = f"{bin_dir}:{os.environ['PATH']}"
    env = {"PATH": fault_path, "_CODING_PREFLIGHT_TEST_FAULT_PATH": fault_path}
    result = run_guard(worktree, *coding_args(worktree), env=env)
    assert_blocked(result, "DIRTY_COUNT_PROBE_FAILED")


def test_blocks_clean_initialized_submodule_without_recovery(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    subrepo = tmp_path / "clean-local-subrepo"
    git(tmp_path, "init", str(subrepo))
    git(subrepo, "config", "user.name", "Preflight Test")
    git(subrepo, "config", "user.email", "preflight@example.invalid")
    (subrepo / "sub.txt").write_text("base\n", encoding="utf-8")
    git(subrepo, "add", "sub.txt")
    git(subrepo, "commit", "-m", "sub base")
    target = tmp_path / "clean-submodule-target"
    git(primary, "worktree", "add", str(target), "-b", "clean-submodule")
    git(target, "-c", "protocol.file.allow=always", "submodule", "add", str(subrepo), "vendor/sub")
    git(target, "add", ".gitmodules", "vendor/sub")
    git(target, "commit", "-m", "add clean submodule")
    result = run_guard(
        worktree, "--expected-workspace", str(worktree),
        "--cleanup-target", str(target), "--destructive-cleanup",
    )
    assert_blocked(result, "INITIALIZED_SUBMODULE_RECOVERY_REQUIRED")


def test_blocks_process_executable_reference(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "exe-ref-target"
    git(primary, "worktree", "add", str(target), "-b", "exe-ref-target")
    executable = target / "worker.bin"
    executable.write_text("binary\n", encoding="utf-8")
    fake_proc = tmp_path / "proc-exe-ref"
    pid_dir = fake_proc / "4242"
    (pid_dir / "fd").mkdir(parents=True)
    (pid_dir / "status").write_text("Name:\ttest\n", encoding="utf-8")
    outside = tmp_path / "outside-exe"
    outside.mkdir()
    (pid_dir / "cwd").symlink_to(outside, target_is_directory=True)
    (pid_dir / "root").symlink_to("/", target_is_directory=True)
    (pid_dir / "exe").symlink_to(executable)
    result = run_guard(
        worktree, "--expected-workspace", str(worktree),
        "--cleanup-target", str(target),
        env={"CODING_PREFLIGHT_TEST_MODE": "1", "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc)},
    )
    assert_blocked(result, "LIVE_PROCESS_REFERENCE_PRESENT")


def test_blocks_malformed_divergence_output(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    env = git_wrapper_env(
        tmp_path,
        'if [[ "$1" == "rev-list" ]]; then printf "garbage output\\n"; exit 0; fi',
    )
    result = run_guard(worktree, *coding_args(worktree), env=env)
    assert_blocked(result, "DIVERGENCE_PROBE_FAILED")


def test_blocks_push_spec_count_parser_failure(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    git(worktree, "config", "remote.origin.push", "refs/heads/feature:refs/heads/review")
    env = git_wrapper_env(
        tmp_path,
        'if [[ "$1" == "config" && " $* " == *'
        '" --get-all remote.origin.push "* ]]; then exit 82; fi',
    )
    result = run_guard(worktree, *coding_args(worktree), env=env)
    assert_blocked(result, "PUSH_CONFIG_PROBE_FAILED")


def test_blocks_untracked_list_probe_failure(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "untracked-probe-target"
    git(primary, "worktree", "add", str(target), "-b", "untracked-probe")
    (target / "new.txt").write_text("preserve\n", encoding="utf-8")
    ref, checksum, coverage, _, archive = write_recovery_evidence(primary, target, tmp_path)
    assert archive is not None
    env = git_wrapper_env(
        tmp_path,
        ('if [[ "$1" == "-C" && "$2" == ' + repr(str(target))
         + ' && "$3" == "ls-files" && "$4" == "-o"'
         + ' && "${5:-}" == "--exclude-standard" ]]; then'
         + ' "$REAL_GIT" "$@"; exit 88; fi'),
        CODING_PREFLIGHT_TEST_MODE="1",
        CODING_PREFLIGHT_PROC_ROOT=str(tmp_path / "fake-proc-untracked"),
    )
    (tmp_path / "fake-proc-untracked").mkdir()
    result = run_guard(
        worktree, "--expected-workspace", str(worktree),
        "--cleanup-target", str(target), "--destructive-cleanup",
        "--archive-ref", ref,
        "--untracked-archive", str(archive),
        "--checksum-evidence", str(checksum),
        "--coverage-evidence", str(coverage),
        env=env,
    )
    assert_blocked(result, "UNTRACKED_PROBE_FAILED")


def test_blocks_final_head_probe_partial_failure(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "final-head-probe-target"
    git(primary, "worktree", "add", str(target), "-b", "final-head-probe")
    ref, checksum, coverage, _, _ = write_recovery_evidence(primary, target, tmp_path)
    env = git_wrapper_env(
        tmp_path,
        ('if [[ "$1" == "-C" && "$2" == ' + repr(str(target))
         + ' && "$3" == "rev-parse" && "$4" == "HEAD" ]]; then'
         + ' "$REAL_GIT" "$@"; exit 89; fi'),
        CODING_PREFLIGHT_TEST_MODE="1",
        CODING_PREFLIGHT_PROC_ROOT=str(tmp_path / "fake-proc-final-head"),
    )
    (tmp_path / "fake-proc-final-head").mkdir()
    result = run_guard(
        worktree, "--expected-workspace", str(worktree),
        "--cleanup-target", str(target), "--destructive-cleanup",
        "--archive-ref", ref,
        "--checksum-evidence", str(checksum),
        "--coverage-evidence", str(coverage),
        env=env,
    )
    assert_blocked(result, "FINAL_TARGET_HEAD_PROBE_FAILED")


def test_blocks_mirror_push_remote(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "remote.origin.mirror", "true")
    result = run_guard(
        worktree,
        *coding_args(worktree),
        "--expected-push-target",
        "origin:refs/heads/feature",
    )
    assert_blocked(result, "MIRROR_PUSH_REMOTE")


def test_blocks_push_follow_tags(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "push.followTags", "true")
    result = run_guard(
        worktree,
        *coding_args(worktree),
        "--expected-push-target",
        "origin:refs/heads/feature",
    )
    assert_blocked(result, "PUSH_FOLLOW_TAGS_ENABLED")


def test_blocks_multiple_push_urls(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    remote = git(worktree, "remote", "get-url", "origin").stdout.strip()
    git(worktree, "config", "--add", "remote.origin.pushurl", remote)
    git(worktree, "config", "--add", "remote.origin.pushurl", remote)
    result = run_guard(
        worktree,
        *coding_args(worktree),
        "--expected-push-target",
        "origin:refs/heads/feature",
    )
    assert_blocked(result, "MULTIPLE_PUSH_URLS")


def test_blocks_maps_reference_under_newline_target(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "maps-newline\ntarget"
    git(primary, "worktree", "add", str(target), "-b", "maps-newline-target")
    mapped = target / "mapped.bin"
    mapped.write_text("mapped\n", encoding="utf-8")
    fake_proc = tmp_path / "proc-maps-newline"
    pid_dir = fake_proc / "4242"
    (pid_dir / "fd").mkdir(parents=True)
    (pid_dir / "status").write_text("Name:\ttest\n", encoding="utf-8")
    outside = tmp_path / "maps-outside"
    outside.mkdir()
    (pid_dir / "cwd").symlink_to(outside, target_is_directory=True)
    (pid_dir / "root").symlink_to("/", target_is_directory=True)
    maps_path = str(mapped).replace("\n", "\\012")
    (pid_dir / "maps").write_text(
        f"00400000-00401000 r--p 00000000 00:00 1 {maps_path}\n",
        encoding="utf-8",
    )
    result = run_guard(
        worktree, "--expected-workspace", str(worktree),
        "--cleanup-target", str(target),
        env={"CODING_PREFLIGHT_TEST_MODE": "1", "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc)},
    )
    assert_blocked(result, "LIVE_PROCESS_REFERENCE_PRESENT")


def test_blocks_empty_pushurl_entry(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "--add", "remote.origin.pushurl", "")
    git(worktree, "config", "--add", "remote.origin.pushurl", "second-destination")
    result = run_guard(
        worktree,
        *coding_args(worktree),
        "--expected-push-target",
        "origin:refs/heads/feature",
    )
    data = assert_blocked(result, "EMPTY_PUSH_URL")
    assert "MULTIPLE_PUSH_URLS" in data["REASONS"].split(",")

def test_blocks_destructive_cleanup_with_staged_index(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "staged-index-target"
    git(primary, "worktree", "add", str(target), "-b", "staged-index-target")
    (target / "tracked.txt").write_text("staged\n", encoding="utf-8")
    git(target, "add", "tracked.txt")
    result = run_guard(
        worktree,
        "--expected-workspace", str(worktree),
        "--cleanup-target", str(target),
        "--destructive-cleanup",
    )
    assert_blocked(result, "STAGED_INDEX_STATE_PRESENT")


def test_blocks_destructive_cleanup_with_unmerged_index(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    git(primary, "checkout", "-b", "cleanup-conflict-side")
    (primary / "tracked.txt").write_text("side\n", encoding="utf-8")
    git(primary, "add", "tracked.txt")
    git(primary, "commit", "-m", "cleanup conflict side")
    git(primary, "checkout", "main")
    target = tmp_path / "unmerged-index-target"
    git(primary, "worktree", "add", str(target), "-b", "unmerged-index-target")
    (target / "tracked.txt").write_text("target\n", encoding="utf-8")
    git(target, "add", "tracked.txt")
    git(target, "commit", "-m", "cleanup conflict target")
    merge = git(target, "merge", "cleanup-conflict-side", check=False)
    assert merge.returncode != 0
    result = run_guard(
        worktree,
        "--expected-workspace", str(worktree),
        "--cleanup-target", str(target),
        "--destructive-cleanup",
    )
    assert_blocked(result, "UNMERGED_INDEX_STATE_PRESENT")


def test_blocks_assume_unchanged_visibility_hazard(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "update-index", "--assume-unchanged", "tracked.txt")
    (worktree / "tracked.txt").write_text("hidden dirty\n", encoding="utf-8")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "INDEX_VISIBILITY_FLAGS_PRESENT")


def test_blocks_skip_worktree_visibility_hazard(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "update-index", "--skip-worktree", "tracked.txt")
    (worktree / "tracked.txt").write_text("hidden dirty\n", encoding="utf-8")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "INDEX_VISIBILITY_FLAGS_PRESENT")


def test_require_clean_ignores_submodule_ignore_all_config(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    subrepo = tmp_path / "ordinary-subrepo"
    git(tmp_path, "init", str(subrepo))
    git(subrepo, "config", "user.name", "Preflight Test")
    git(subrepo, "config", "user.email", "preflight@example.invalid")
    (subrepo / "sub.txt").write_text("base\n", encoding="utf-8")
    git(subrepo, "add", "sub.txt")
    git(subrepo, "commit", "-m", "sub base")
    git(
        worktree,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(subrepo),
        "vendor/sub",
    )
    git(worktree, "add", ".gitmodules", "vendor/sub")
    git(worktree, "commit", "-m", "add ordinary submodule")
    git(worktree, "config", "submodule.vendor/sub.ignore", "all")
    (worktree / "vendor" / "sub" / "sub.txt").write_text(
        "hidden dirty\n", encoding="utf-8"
    )
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "DIRTY_TRACKED")


def test_blocks_branch_probe_failure_even_when_detached_allowed(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    env = git_wrapper_env(
        tmp_path,
        'if [[ "$1" == "symbolic-ref" ]]; then exit 81; fi',
    )
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--allow-detached",
        env=env,
    )
    assert_blocked(result, "BRANCH_PROBE_FAILED")


def test_blocks_configured_upstream_resolution_probe_failure(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    env = git_wrapper_env(
        tmp_path,
        'if [[ "$1" == "rev-parse" && "$2" == "--abbrev-ref" ]]; then exit 82; fi',
    )
    result = run_guard(worktree, "--expected-workspace", str(worktree), env=env)
    assert_blocked(result, "UPSTREAM_PROBE_FAILED")


def test_blocks_upstream_config_probe_failure_without_upstream_gate(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    env = git_wrapper_env(
        tmp_path,
        (
            'if [[ "$1" == "rev-parse" && "$2" == "--abbrev-ref" ]]; then exit 82; fi\n'
            'if [[ "$1" == "config" && "$2" == "--get" '
            '&& "$3" == "branch.feature.remote" ]]; then exit 83; fi'
        ),
    )
    result = run_guard(worktree, "--expected-workspace", str(worktree), env=env)
    assert_blocked(result, "UPSTREAM_CONFIG_PROBE_FAILED")


def test_preflight_never_executes_configured_fsmonitor_helper(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    marker = tmp_path / "fsmonitor-ran"
    helper = tmp_path / "fsmonitor-helper.sh"
    helper.write_text(
        f"#!/bin/sh\ntouch {str(marker)!r}\nexit 1\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    git(worktree, "config", "core.fsmonitor", str(helper))
    result = run_guard(worktree, *coding_args(worktree))
    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()


def test_cleanup_never_executes_external_diff_helper(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "external-diff-target"
    git(primary, "worktree", "add", str(target), "-b", "external-diff-target")
    (target / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    ref, checksum, coverage, patch, _ = write_recovery_evidence(
        primary, target, tmp_path
    )
    marker = tmp_path / "external-diff-ran"
    helper = tmp_path / "external-diff.sh"
    helper.write_text(
        f"#!/bin/sh\ntouch {str(marker)!r}\nexit 0\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    git(target, "config", "diff.external", str(helper))
    result = run_guard(
        worktree,
        "--expected-workspace", str(worktree),
        "--cleanup-target", str(target),
        "--destructive-cleanup",
        "--archive-ref", ref,
        "--tracked-patch", str(patch),
        "--checksum-evidence", str(checksum),
        "--coverage-evidence", str(coverage),
    )
    assert not marker.exists(), result.stdout + result.stderr


def test_cleanup_never_executes_textconv_helper(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "textconv-target"
    git(primary, "worktree", "add", str(target), "-b", "textconv-target")
    (target / ".gitattributes").write_text("tracked.txt diff=probe\n", encoding="utf-8")
    git(target, "add", ".gitattributes")
    git(target, "commit", "-m", "configure diff attribute")
    (target / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    ref, checksum, coverage, patch, _ = write_recovery_evidence(
        primary, target, tmp_path
    )
    marker = tmp_path / "textconv-ran"
    helper = tmp_path / "textconv.sh"
    helper.write_text(
        f"#!/bin/sh\ntouch {str(marker)!r}\ncat \"$1\"\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    git(target, "config", "diff.probe.textconv", str(helper))
    result = run_guard(
        worktree,
        "--expected-workspace", str(worktree),
        "--cleanup-target", str(target),
        "--destructive-cleanup",
        "--archive-ref", ref,
        "--tracked-patch", str(patch),
        "--checksum-evidence", str(checksum),
        "--coverage-evidence", str(coverage),
    )
    assert not marker.exists(), result.stdout + result.stderr


def test_blocks_multiple_fallback_push_urls(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "--unset-all", "remote.origin.pushurl", check=False)
    remote = git(worktree, "remote", "get-url", "origin").stdout.strip()
    git(worktree, "config", "--add", "remote.origin.url", remote)
    result = run_guard(
        worktree,
        *coding_args(worktree),
        "--expected-push-target",
        "origin:refs/heads/feature",
    )
    assert_blocked(result, "MULTIPLE_PUSH_URLS")


def test_blocks_missing_effective_push_url(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "--unset-all", "remote.origin.pushurl", check=False)
    git(worktree, "config", "--unset-all", "remote.origin.url")
    result = run_guard(
        worktree,
        *coding_args(worktree),
        "--expected-push-target",
        "origin:refs/heads/feature",
    )
    assert_blocked(result, "PUSH_URL_MISSING")


def test_blocks_forced_push_refspec(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "--unset-all", "remote.origin.push", check=False)
    git(
        worktree,
        "config",
        "--add",
        "remote.origin.push",
        "+refs/heads/feature:refs/heads/review",
    )
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "HAZARDOUS_PUSH_REFSPEC")


def test_blocks_deletion_push_refspec(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "--unset-all", "remote.origin.push", check=False)
    git(worktree, "config", "--add", "remote.origin.push", ":refs/heads/review")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "HAZARDOUS_PUSH_REFSPEC")


def test_blocks_conflicting_duplicate_coverage_evidence(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "duplicate-coverage-target"
    git(primary, "worktree", "add", str(target), "-b", "duplicate-coverage")
    ref, checksum, coverage, _, _ = write_recovery_evidence(primary, target, tmp_path)
    with coverage.open("a", encoding="utf-8") as stream:
        stream.write("COVERAGE_BAD=1\nTARGET_HEAD=deadbeef\n")
    checksum.write_text(
        subprocess.run(
            ["sha256sum", str(coverage)], capture_output=True, text=True, check=True
        ).stdout,
        encoding="utf-8",
    )
    fake_proc = tmp_path / "proc-duplicate-coverage"
    fake_proc.mkdir()
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        },
    )
    assert_blocked(result, "COVERAGE_EVIDENCE_AMBIGUOUS")


def test_destructive_cleanup_requires_atomic_executor(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "atomicity-target"
    git(primary, "worktree", "add", str(target), "-b", "atomicity-target")
    ref, checksum, coverage, _, _ = write_recovery_evidence(primary, target, tmp_path)
    fake_proc = tmp_path / "proc-atomicity"
    fake_proc.mkdir()
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        },
    )
    data = assert_blocked(result, "DESTRUCTIVE_CLEANUP_ATOMICITY_UNPROVEN")
    assert data["ARCHIVE_REQUIREMENT_STATE"] == "PASS"


def test_scrubs_inherited_git_index_file(repo: tuple[Path, Path], tmp_path: Path) -> None:
    _, worktree = repo
    index_raw = git(worktree, "rev-parse", "--git-path", "index").stdout.strip()
    index_path = Path(index_raw)
    if not index_path.is_absolute():
        index_path = worktree / index_path
    clean_index = tmp_path / "clean-index"
    shutil.copy2(index_path, clean_index)
    (worktree / "tracked.txt").write_text("staged\n", encoding="utf-8")
    git(worktree, "add", "tracked.txt")
    (worktree / "tracked.txt").write_text("base\n", encoding="utf-8")
    result = run_guard(
        worktree,
        *coding_args(worktree),
        env={"GIT_INDEX_FILE": str(clean_index)},
    )
    assert_blocked(result, "DIRTY_TRACKED")


def test_blocks_configured_clean_filter_without_execution(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    attrs = worktree / ".gitattributes"
    attrs.write_text("tracked.txt filter=evil\n", encoding="utf-8")
    git(worktree, "add", ".gitattributes")
    git(worktree, "commit", "-m", "add filter attributes")
    marker = tmp_path / "clean-filter-ran"
    helper = tmp_path / "evil-clean.sh"
    helper.write_text(
        f"#!/bin/sh\ntouch {str(marker)!r}\ncat\n", encoding="utf-8"
    )
    helper.chmod(0o755)
    git(worktree, "config", "filter.evil.clean", str(helper))
    git(worktree, "config", "filter.evil.required", "true")
    os.utime(worktree / "tracked.txt", None)
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "GIT_FILTER_CONFIGURATION_PRESENT")
    assert not marker.exists()


def test_blocks_duplicate_worktree_metadata(repo: tuple[Path, Path], tmp_path: Path) -> None:
    _, worktree = repo
    head = git(worktree, "rev-parse", "HEAD").stdout.strip()
    record = [
        f"worktree {worktree}",
        f"HEAD {head}",
        "branch refs/heads/feature",
        "",
    ]
    fields = record + record
    quoted = " ".join(repr(field) for field in fields)
    body = (
        'if [[ "$1" == "worktree" && "$2" == "list" ]]; then '
        f'printf "%s\\0" {quoted}; exit 0; fi'
    )
    env = git_wrapper_env(tmp_path, body)
    result = run_guard(worktree, *coding_args(worktree), env=env)
    assert_blocked(result, "WORKTREE_METADATA_MALFORMED")


def test_revalidates_coding_state_before_pass(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    marker = tmp_path / "mutated-after-status"
    tracked = worktree / "tracked.txt"
    body = (
        'if [[ "$1" == "worktree" && "$2" == "list" ]]; then '
        '"$REAL_GIT" "$@"; rc=$?; '
        f'if [[ ! -e {str(marker)!r} ]]; then touch {str(marker)!r}; '
        f'printf "changed\\n" > {str(tracked)!r}; fi; exit "$rc"; fi'
    )
    env = git_wrapper_env(tmp_path, body)
    result = run_guard(worktree, *coding_args(worktree), env=env)
    assert_blocked(result, "CODING_STATE_CHANGED")


def test_blocks_maps_reference_with_tab_and_backslash_target(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "maps-tab\ttarget\\segment"
    git(primary, "worktree", "add", str(target), "-b", "maps-tab-target")
    mapped = target / "mapped.bin"
    mapped.write_text("mapped\n", encoding="utf-8")
    fake_proc = tmp_path / "proc-maps-tab"
    pid_dir = fake_proc / "4343"
    (pid_dir / "fd").mkdir(parents=True)
    (pid_dir / "status").write_text("Name:\ttest\n", encoding="utf-8")
    outside = tmp_path / "maps-outside-tab"
    outside.mkdir()
    (pid_dir / "cwd").symlink_to(outside, target_is_directory=True)
    (pid_dir / "root").symlink_to("/", target_is_directory=True)
    maps_path = str(mapped)
    (pid_dir / "maps").write_text(
        f"00400000-00401000 r--p 00000000 00:00 1 {maps_path}\n",
        encoding="utf-8",
    )
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        },
    )
    assert_blocked(result, "LIVE_PROCESS_REFERENCE_PRESENT")


def test_recovery_evidence_supports_newline_paths_and_names(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "recovery\npath"
    git(primary, "worktree", "add", str(target), "-b", "recovery-newline")
    (target / "name\nwith-newline.txt").write_text("preserve\n", encoding="utf-8")
    ref, checksum, coverage, _, archive = write_recovery_evidence(
        primary, target, tmp_path
    )
    assert archive is not None
    fake_proc = tmp_path / "proc-recovery-newline"
    fake_proc.mkdir()
    result = run_guard(
        worktree,
        "--expected-workspace",
        str(worktree),
        "--cleanup-target",
        str(target),
        "--destructive-cleanup",
        "--archive-ref",
        ref,
        "--untracked-archive",
        str(archive),
        "--checksum-evidence",
        str(checksum),
        "--coverage-evidence",
        str(coverage),
        env={
            "CODING_PREFLIGHT_TEST_MODE": "1",
            "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
        },
    )
    data = assert_blocked(result, "DESTRUCTIVE_CLEANUP_ATOMICITY_UNPROVEN")
    assert data["ARCHIVE_REQUIREMENT_STATE"] == "PASS"


def test_scrubs_remaining_git_local_environment(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    env = git_wrapper_env(
        tmp_path,
        'if [[ -n "${GIT_IMPLICIT_WORK_TREE+x}" || '
        '"${GIT_NO_REPLACE_OBJECTS:-}" != "1" ]]; then exit 79; fi',
        GIT_IMPLICIT_WORK_TREE="0",
        GIT_NO_REPLACE_OBJECTS="spoofed",
    )
    result = run_guard(worktree, *coding_args(worktree), env=env)
    assert result.returncode == 0, result.stdout + result.stderr


def test_blocks_incomplete_and_duplicate_worktree_fields(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    head = git(worktree, "rev-parse", "HEAD").stdout.strip()
    fields = [f"worktree {worktree}", f"HEAD {head}", "locked one", "locked two", ""]
    quoted = " ".join(repr(field) for field in fields)
    body = (
        'if [[ "$1" == "worktree" && "$2" == "list" ]]; then '
        f'printf "%s\\0" {quoted}; exit 0; fi'
    )
    result = run_guard(worktree, *coding_args(worktree), env=git_wrapper_env(tmp_path, body))
    assert_blocked(result, "WORKTREE_METADATA_MALFORMED")


def test_blocks_kernel_realistic_maps_with_newline_tab_backslash(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "maps\nreal\ttarget\\segment"
    git(primary, "worktree", "add", str(target), "-b", "maps-real-target")
    mapped = target / "mapped.bin"
    mapped.write_text("mapped\n", encoding="utf-8")
    fake_proc = tmp_path / "proc-maps-real"
    pid_dir = fake_proc / "4545"
    (pid_dir / "fd").mkdir(parents=True)
    (pid_dir / "status").write_text("Name:\ttest\n", encoding="utf-8")
    outside = tmp_path / "maps-real-outside"
    outside.mkdir()
    (pid_dir / "cwd").symlink_to(outside, target_is_directory=True)
    (pid_dir / "root").symlink_to("/", target_is_directory=True)
    maps_path = str(mapped).replace("\n", "\\012")
    (pid_dir / "maps").write_text(
        f"00400000-00401000 r--p 00000000 00:00 1 {maps_path}\n", encoding="utf-8"
    )
    result = run_guard(
        worktree, "--expected-workspace", str(worktree), "--cleanup-target", str(target),
        env={"CODING_PREFLIGHT_TEST_MODE": "1", "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc)},
    )
    assert_blocked(result, "LIVE_PROCESS_REFERENCE_PRESENT")


def test_cleanup_never_executes_inherited_tar_options(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "tar-options-target"
    git(primary, "worktree", "add", str(target), "-b", "tar-options-target")
    (target / "new.txt").write_text("preserve\n", encoding="utf-8")
    ref, checksum, coverage, _, archive = write_recovery_evidence(primary, target, tmp_path)
    assert archive is not None
    marker = tmp_path / "tar-options-ran"
    helper = tmp_path / "tar-options-helper.sh"
    helper.write_text(f"#!/bin/sh\ntouch {str(marker)!r}\n", encoding="utf-8")
    helper.chmod(0o755)
    fake_proc = tmp_path / "proc-tar-options"
    fake_proc.mkdir()
    result = run_guard(
        worktree, "--expected-workspace", str(worktree), "--cleanup-target", str(target),
        "--destructive-cleanup", "--archive-ref", ref, "--untracked-archive", str(archive),
        "--checksum-evidence", str(checksum), "--coverage-evidence", str(coverage),
        env={"CODING_PREFLIGHT_TEST_MODE": "1", "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc),
             "TAR_OPTIONS": f"--checkpoint=1 --checkpoint-action=exec={helper}"},
    )
    assert result.returncode != 0
    assert not marker.exists()


def test_cleanup_python_runs_isolated_from_repository(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "python-isolated-target"
    git(primary, "worktree", "add", str(target), "-b", "python-isolated-target")
    (target / "new.txt").write_text("preserve\n", encoding="utf-8")
    ref, checksum, coverage, _, archive = write_recovery_evidence(primary, target, tmp_path)
    assert archive is not None
    marker = tmp_path / "python-import-ran"
    malicious = worktree / "tarfile.py"
    malicious.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('blocked')\n",
        encoding="utf-8",
    )
    fake_proc = tmp_path / "proc-python-isolated"
    fake_proc.mkdir()
    result = run_guard(
        worktree, "--expected-workspace", str(worktree), "--cleanup-target", str(target),
        "--destructive-cleanup", "--archive-ref", ref, "--untracked-archive", str(archive),
        "--checksum-evidence", str(checksum), "--coverage-evidence", str(coverage),
        env={"CODING_PREFLIGHT_TEST_MODE": "1", "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc)},
    )
    assert result.returncode != 0
    assert not marker.exists()


def test_checksum_manifest_supports_escaped_evidence_path(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "checksum-target"
    git(primary, "worktree", "add", str(target), "-b", "checksum-target")
    ref, checksum, coverage, _, _ = write_recovery_evidence(primary, target, tmp_path)
    escaped_coverage = tmp_path / "coverage\nwith\\slash.txt"
    coverage.rename(escaped_coverage)
    checksum.write_text(
        subprocess.run(
            ["sha256sum", str(escaped_coverage)], capture_output=True, text=True, check=True
        ).stdout,
        encoding="utf-8",
    )
    fake_proc = tmp_path / "proc-checksum-path"
    fake_proc.mkdir()
    result = run_guard(
        worktree, "--expected-workspace", str(worktree), "--cleanup-target", str(target),
        "--destructive-cleanup", "--archive-ref", ref,
        "--checksum-evidence", str(checksum), "--coverage-evidence", str(escaped_coverage),
        env={"CODING_PREFLIGHT_TEST_MODE": "1", "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc)},
    )
    data = assert_blocked(result, "DESTRUCTIVE_CLEANUP_ATOMICITY_UNPROVEN")
    assert data["ARCHIVE_REQUIREMENT_STATE"] == "PASS"


def test_scrubs_inherited_git_exec_path(repo: tuple[Path, Path], tmp_path: Path) -> None:
    _, worktree = repo
    marker = tmp_path / "git-submodule-ran"
    fake_exec = tmp_path / "git-exec"
    fake_exec.mkdir()
    helper = fake_exec / "git-submodule"
    real_exec = git(worktree, "--exec-path").stdout.strip()
    real_submodule = str(Path(real_exec) / "git-submodule")
    helper.write_text(
        f"#!/bin/sh\ntouch {str(marker)!r}\nexec {real_submodule!r} \"$@\"\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    result = run_guard(worktree, *coding_args(worktree), env={"GIT_EXEC_PATH": str(fake_exec)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()


def test_blocks_retargeted_push_url(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    expected = git(worktree, "remote", "get-url", "origin").stdout.strip()
    git(worktree, "config", "remote.origin.url", "/tmp/attacker.git")
    result = run_guard(worktree, *coding_args(worktree, expected_push_url=expected))
    assert_blocked(result, "PUSH_URL_MISMATCH")


def test_blocks_valid_but_unexpected_git_identity(repo: tuple[Path, Path]) -> None:
    _, worktree = repo
    git(worktree, "config", "user.email", "other@example.invalid")
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "GIT_IDENTITY_MISMATCH")


def test_revalidates_policy_values_before_pass(repo: tuple[Path, Path], tmp_path: Path) -> None:
    _, worktree = repo
    marker = tmp_path / "policy-mutated"
    body = (
        'if [[ "$1" == "worktree" && "$2" == "list" ]]; then '
        '"$REAL_GIT" "$@"; rc=$?; '
        f'if [[ ! -e {str(marker)!r} ]]; then touch {str(marker)!r}; '
        '"$REAL_GIT" config remote.origin.url /tmp/retargeted-after-probe.git; fi; '
        'exit "$rc"; fi'
    )
    result = run_guard(worktree, *coding_args(worktree), env=git_wrapper_env(tmp_path, body))
    assert_blocked(result, "CODING_POLICY_CHANGED")


def test_checksum_manifest_escape_parser_has_no_backslash_newline_collision(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    target = tmp_path / "checksum-collision-target"
    git(primary, "worktree", "add", str(target), "-b", "checksum-collision")
    ref, _, coverage, _, _ = write_recovery_evidence(primary, target, tmp_path)
    expected_coverage = tmp_path / "evidence\\\ncoverage"
    decoy_coverage = tmp_path / "evidence\\ncoverage"
    expected_coverage.write_bytes(coverage.read_bytes())
    decoy_coverage.write_bytes(coverage.read_bytes())
    checksum = tmp_path / "collision.sha256"
    checksum.write_text(
        subprocess.run(
            ["sha256sum", str(decoy_coverage)], capture_output=True, text=True, check=True
        ).stdout,
        encoding="utf-8",
    )
    fake_proc = tmp_path / "proc-checksum-collision"
    fake_proc.mkdir()
    result = run_guard(
        worktree,
        "--expected-workspace", str(worktree),
        "--cleanup-target", str(target),
        "--destructive-cleanup", "--archive-ref", ref,
        "--checksum-evidence", str(checksum),
        "--coverage-evidence", str(expected_coverage),
        env={"CODING_PREFLIGHT_TEST_MODE": "1", "CODING_PREFLIGHT_PROC_ROOT": str(fake_proc)},
    )
    assert_blocked(result, "CHECKSUM_COVERAGE_MISSING")


def test_blocks_retargeted_worktree_admin_gitdir(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    duplicate = tmp_path / "duplicate-admin-wt"
    added = git(
        primary, "worktree", "add", "--force", "--force",
        str(duplicate), "feature", check=False,
    )
    if added.returncode != 0:
        pytest.skip("installed Git does not permit duplicate branch worktrees")
    duplicate_git_dir = git(
        duplicate, "rev-parse", "--path-format=absolute", "--git-dir"
    ).stdout.strip()
    (worktree / ".git").write_text(
        f"gitdir: {duplicate_git_dir}\n", encoding="utf-8"
    )
    result = run_guard(worktree, *coding_args(worktree))
    assert_blocked(result, "WORKTREE_ADMIN_MISMATCH")


def test_scrubs_inherited_git_trace_side_effect(repo: tuple[Path, Path], tmp_path: Path) -> None:
    _, worktree = repo
    trace_file = tmp_path / "git-trace.log"
    result = run_guard(
        worktree,
        *coding_args(worktree),
        env={"GIT_TRACE": str(trace_file)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not trace_file.exists()


def test_revalidates_worktree_scoped_push_policy(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    git(worktree, "config", "extensions.worktreeConfig", "true")
    marker = tmp_path / "worktree-config-mutated"
    body = (
        'if [[ "$1" == "status" && ! -e ' + repr(str(marker)) + ' ]]; then '
        '"$REAL_GIT" "$@"; rc=$?; '
        '"$REAL_GIT" config --worktree push.followTags true; '
        'touch ' + repr(str(marker)) + '; exit "$rc"; fi'
    )
    env = git_wrapper_env(tmp_path, body)
    result = run_guard(worktree, *coding_args(worktree), env=env)
    assert_blocked(result, "CODING_POLICY_CHANGED")


def test_blocks_empty_branch_worktree_metadata(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    git(worktree, "checkout", "--detach")
    head = git(worktree, "rev-parse", "HEAD").stdout.strip()
    fields = [f"worktree {worktree}", f"HEAD {head}", "branch ", ""]
    quoted = " ".join(repr(field) for field in fields)
    body = (
        'if [[ "$1" == "worktree" && "$2" == "list" ]]; then '
        f'printf "%s\\0" {quoted}; exit 0; fi'
    )
    env = git_wrapper_env(tmp_path, body)
    result = run_guard(
        worktree,
        "--expected-workspace", str(worktree),
        "--require-isolation", "--require-clean", "--allow-detached",
        env=env,
    )
    assert_blocked(result, "WORKTREE_METADATA_MALFORMED")


def test_ignores_bash_env_and_untrusted_path_before_guard_body(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    bash_env_marker = tmp_path / "bash-env-ran"
    bash_env = tmp_path / "bash-env.sh"
    bash_env.write_text(f"touch {bash_env_marker!s}\n", encoding="utf-8")

    fake_bin = tmp_path / "fake-startup-bin"
    fake_bin.mkdir()
    fake_bash_marker = tmp_path / "fake-bash-ran"
    fake_bash = fake_bin / "bash"
    fake_bash.write_text(
        "#!/bin/sh\n"
        f"touch {fake_bash_marker!s}\n"
        "exec /bin/bash \"$@\"\n",
        encoding="utf-8",
    )
    fake_bash.chmod(0o755)

    result = run_guard(
        worktree,
        *coding_args(worktree),
        env={
            "BASH_ENV": str(bash_env),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not bash_env_marker.exists()
    assert not fake_bash_marker.exists()


def test_blocks_inherited_dynamic_loader_environment(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    result = run_guard(
        worktree,
        *coding_args(worktree),
        env={"LD_PRELOAD": str(tmp_path / "nonexistent-preload.so")},
    )
    assert_blocked(result, "UNTRUSTED_STARTUP_ENV")


def test_static_controller_rejects_preload_before_its_constructor_runs(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    controller = build_controller(tmp_path)
    marker = tmp_path / "preload-constructor-ran"
    preload_source = tmp_path / "preload.c"
    preload = tmp_path / "preload.so"
    preload_constructor = (
        "__attribute__((constructor)) static void ran(void) "
        f"{{ close(creat({str(marker)!r}, 0600)); }}\n"
    )
    preload_source.write_text(
        "#include <fcntl.h>\n"
        "#include <unistd.h>\n"
        + preload_constructor,
        encoding="utf-8",
    )
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-o", str(preload), str(preload_source)],
        check=True,
        capture_output=True,
        text=True,
    )
    result = run_controller(
        controller,
        worktree,
        worktree,
        "rev-parse",
        "--show-toplevel",
        env={"LD_PRELOAD": str(preload)},
    )
    assert result.returncode != 0
    assert "CONTROLLER=BLOCKED" in result.stdout
    assert "UNSAFE_ENVIRONMENT" in result.stdout
    assert not marker.exists()


def test_controller_rejects_inherited_git_target_override(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    controller = build_controller(tmp_path)
    result = run_controller(
        controller,
        worktree,
        worktree,
        "rev-parse",
        "--show-toplevel",
        env={"GIT_DIR": str(primary / ".git")},
    )
    assert result.returncode != 0
    assert "CONTROLLER=BLOCKED" in result.stdout
    assert "UNSAFE_ENVIRONMENT" in result.stdout


def test_controller_discards_harmless_git_pager_environment(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    guard = worktree / "scripts" / "coding_preflight.sh"
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_bytes(GUARD.read_bytes())
    guard.chmod(0o755)
    controller = build_controller(tmp_path)
    result = run_controller(
        controller,
        worktree,
        worktree,
        "rev-parse",
        "--show-toplevel",
        env={"GIT_PAGER": "cat"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == str(worktree.resolve())


def test_controller_rebinds_and_executes_git_in_expected_workspace(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    primary, worktree = repo
    guard = worktree / "scripts" / "coding_preflight.sh"
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_bytes(GUARD.read_bytes())
    guard.chmod(0o755)
    controller = build_controller(tmp_path)
    result = run_controller(
        controller, primary, worktree, "rev-parse", "--show-toplevel"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1] == str(worktree.resolve())


def test_agents_requires_authoritative_controller_workflow() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "`/usr/local/libexec/anh-duong/coding-preflight-controller` directly" in agents
    assert "exact `--expected-workspace`, policy flags, and `-- git ...` operation" in agents
    expected_guard_text = (
        "hard-binds the root-owned system guard installed from canonical "
        "`scripts/coding_preflight.sh`"
    )
    assert expected_guard_text in agents
    assert "immediately `exec`s the requested Git operation" in agents
    assert "never invoke the guard, `bash`, or `env` directly" in agents


def test_controller_rejects_caller_selected_guard_path(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    controller = build_controller(tmp_path)
    result = subprocess.run(
        [
            str(controller),
            "--expected-workspace",
            str(worktree),
            "--guard",
            "/dev/null",
            "--",
            "git",
            "rev-parse",
            "--show-toplevel",
        ],
        cwd=worktree,
        capture_output=True,
        text=True,
        env=controller_env(),
        check=False,
    )
    assert result.returncode != 0
    assert "CONTROLLER=BLOCKED" in result.stdout
    assert "INVALID_INVOCATION" in result.stdout


@pytest.mark.parametrize("policy_flag", ["--help", "-h"])
def test_controller_rejects_policy_short_circuit_before_git_execution(
    repo: tuple[Path, Path], tmp_path: Path, policy_flag: str
) -> None:
    _, worktree = repo
    controller = build_controller(tmp_path)
    result = subprocess.run(
        [
            str(controller),
            "--expected-workspace",
            str(worktree),
            policy_flag,
            "--",
            "git",
            "rev-parse",
            "--show-toplevel",
        ],
        cwd=worktree,
        capture_output=True,
        text=True,
        env=controller_env(),
        check=False,
    )
    assert result.returncode != 0
    assert "CONTROLLER=BLOCKED" in result.stdout
    assert "INVALID_INVOCATION" in result.stdout
    assert str(worktree.resolve()) not in result.stdout


@pytest.mark.parametrize(
    ("retarget", "args"),
    [
        ("-C", ("-C", "/tmp/attacker", "rev-parse", "--show-toplevel")),
        ("--git-dir", ("--git-dir=/tmp/attacker", "rev-parse", "--show-toplevel")),
        ("--work-tree", ("--work-tree=/tmp/attacker", "rev-parse", "--show-toplevel")),
        ("--namespace", ("--namespace=attacker", "rev-parse", "--show-toplevel")),
        ("--exec-path", ("--exec-path=/tmp/attacker", "rev-parse", "--show-toplevel")),
        ("--super-prefix", ("--super-prefix=/tmp/attacker", "rev-parse", "--show-toplevel")),
        (
            "-c remote.origin.pushurl",
            ("-c", "remote.origin.pushurl=/tmp/attacker.git", "rev-parse", "--show-toplevel"),
        ),
        (
            "--config-env separate",
            ("--config-env", "remote.origin.pushurl=ATTACKER_URL", "rev-parse", "--show-toplevel"),
        ),
        (
            "--config-env assigned",
            ("--config-env=remote.origin.pushurl=ATTACKER_URL", "rev-parse", "--show-toplevel"),
        ),
        ("--bare", ("--bare", "rev-parse", "--show-toplevel")),
    ],
)
def test_controller_blocks_git_retargeting_options(
    repo: tuple[Path, Path], tmp_path: Path, retarget: str, args: tuple[str, ...]
) -> None:
    _, worktree = repo
    controller = build_controller(tmp_path)
    result = run_controller(controller, worktree, worktree, *args)
    assert result.returncode != 0
    assert "CONTROLLER=BLOCKED" in result.stdout
    assert "GIT_RETARGET_OPTION" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("push", "--repo=https://attacker.invalid/repo.git"),
        ("push", "--repo", "https://attacker.invalid/repo.git"),
        ("push", "--rep=https://attacker.invalid/repo.git"),
        ("push", "--rep", "https://attacker.invalid/repo.git"),
        ("push", "https://attacker.invalid/repo.git"),
    ],
)
def test_controller_blocks_push_repository_override(
    repo: tuple[Path, Path], tmp_path: Path, args: tuple[str, ...]
) -> None:
    _, worktree = repo
    controller = build_controller(tmp_path)
    result = run_controller(controller, worktree, worktree, *args)
    assert result.returncode != 0
    assert "CONTROLLER=BLOCKED" in result.stdout
    assert "GIT_PUSH_REPOSITORY_OVERRIDE" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("--git-dir=/tmp/attacker", "status"),
        ("-c", "alias.sneak=push", "sneak", "https://attacker.invalid/repo.git"),
        ("push", "--repo=https://attacker.invalid/repo.git"),
        ("push", "--rep=https://attacker.invalid/repo.git"),
        ("push", "https://attacker.invalid/repo.git"),
    ],
)
def test_direct_guard_enforces_git_operation_boundary(
    repo: tuple[Path, Path], args: tuple[str, ...]
) -> None:
    _, worktree = repo
    result = subprocess.run(
        [
            "/bin/bash",
            "-p",
            str(GUARD),
            "--expected-workspace",
            str(worktree),
            "--",
            "git",
            *args,
        ],
        cwd=worktree,
        capture_output=True,
        text=True,
        env=controller_env(),
        check=False,
    )
    assert result.returncode != 0
    assert "INVALID_INVOCATION" in result.stdout


def test_controller_rejects_local_git_alias_as_non_builtin_subcommand(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    git(worktree, "config", "alias.sneak", "push")
    controller = build_controller(tmp_path)
    result = run_controller(
        controller,
        worktree,
        worktree,
        "sneak",
        "https://attacker.invalid/repo.git",
    )
    assert result.returncode != 0
    assert "INVALID_INVOCATION" in result.stdout
    assert "git_subcommand_not_builtin" in result.stdout


def test_controller_allows_subcommand_c_option(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    guard = worktree / "scripts" / "coding_preflight.sh"
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_bytes(GUARD.read_bytes())
    guard.chmod(0o755)
    controller = build_controller(tmp_path)
    result = run_controller(controller, worktree, worktree, "show", "-c", "HEAD")
    assert result.returncode == 0, result.stdout + result.stderr


def test_controller_does_not_execute_git_after_guard_returns_success(
    repo: tuple[Path, Path], tmp_path: Path
) -> None:
    _, worktree = repo
    workspace_guard = worktree / "scripts" / "coding_preflight.sh"
    workspace_guard.parent.mkdir(parents=True, exist_ok=True)
    workspace_guard.write_bytes(GUARD.read_bytes())
    workspace_guard.chmod(0o755)
    fake_guard = tmp_path / "trusted-guard.sh"
    fake_guard.write_text("#!/bin/bash -p\nexit 0\n", encoding="utf-8")
    fake_guard.chmod(0o755)
    controller = build_controller(tmp_path, fake_guard)
    result = run_controller(controller, worktree, worktree, "rev-parse", "--show-toplevel")
    assert result.returncode == 0
    assert (
        not result.stdout.splitlines()
        or result.stdout.splitlines()[-1] != str(worktree.resolve())
    )


def test_guard_executes_git_after_successful_final_validation(
    repo: tuple[Path, Path]
) -> None:
    _, worktree = repo
    result = subprocess.run(
        ["/bin/bash", "-p", str(GUARD), "--expected-workspace", str(worktree),
         "--", "git", "rev-parse", "--show-toplevel"],
        cwd=worktree, capture_output=True, text=True, env=controller_env(), check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PREFLIGHT=PASS" in result.stdout
    assert result.stdout.splitlines()[-1] == str(worktree.resolve())


def test_controller_defaults_to_system_managed_guard_and_installer_contract() -> None:
    source = CONTROLLER_SOURCE.read_text(encoding="utf-8")
    installer = ROOT / "scripts" / "agent" / "install_coding_preflight_controller.sh"
    assert 'TRUSTED_GUARD_PATH "/usr/local/libexec/anh-duong/coding_preflight.sh"' in source
    assert installer.exists()
    text = installer.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[2] == 'PATH="/usr/bin:/bin"'
    assert lines[3] == "export PATH"
    assert 'TMP="$(/usr/bin/mktemp -d -p /tmp)"' in text
    assert "/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C LANG=C /usr/bin/gcc -static" in text
    assert "install -o root -g root -m 0755" in text
    assert "coding_preflight.sh" in text
