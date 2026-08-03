from pathlib import Path

from app.policy.path_scope import WorkspacePathPolicy


def test_absolute_path_inside_allowed_root_is_allowed(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    result = WorkspacePathPolicy((allowed,)).check(
        allowed / "project" / "file.md"
    )

    assert result.allowed is True
    assert result.normalized_path == (
        allowed / "project" / "file.md"
    ).resolve(strict=False)


def test_relative_path_is_resolved_against_workspace(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    workspace = allowed / "project"
    workspace.mkdir(parents=True)

    result = WorkspacePathPolicy((allowed,)).check(
        Path("docs/spec.md"),
        workspace_root=workspace,
    )

    assert result.allowed is True
    assert result.normalized_path == (
        workspace / "docs/spec.md"
    ).resolve(strict=False)


def test_path_outside_allowed_roots_is_denied(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside" / "secret.txt"
    allowed.mkdir()

    result = WorkspacePathPolicy((allowed,)).check(outside)

    assert result.allowed is False
    assert result.rule_id == "path.outside_allowlist"


def test_parent_traversal_out_of_workspace_is_denied(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    workspace = allowed / "project"
    workspace.mkdir(parents=True)

    result = WorkspacePathPolicy((allowed,)).check(
        Path("../../outside.txt"),
        workspace_root=workspace,
    )

    assert result.allowed is False
    assert result.rule_id == "path.outside_workspace"


def test_sibling_workspace_escape_is_denied(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    workspace = allowed / "project-a"
    workspace.mkdir(parents=True)

    result = WorkspacePathPolicy((allowed,)).check(
        Path("../project-b/file.md"),
        workspace_root=workspace,
    )

    assert result.allowed is False
    assert result.rule_id == "path.outside_workspace"


def test_symlink_escape_is_denied(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (allowed / "escape").symlink_to(
        outside,
        target_is_directory=True,
    )

    result = WorkspacePathPolicy((allowed,)).check(
        allowed / "escape" / "secret.txt"
    )

    assert result.allowed is False
    assert result.rule_id == "path.outside_allowlist"


def test_windows_path_is_rejected_in_wsl_policy(
    tmp_path: Path,
) -> None:
    result = WorkspacePathPolicy((tmp_path,)).check(
        Path(r"F:\AIOS\project\file.md")
    )

    assert result.allowed is False
    assert result.rule_id == "path.windows_format"


def test_relative_path_without_workspace_is_denied(
    tmp_path: Path,
) -> None:
    result = WorkspacePathPolicy((tmp_path,)).check(
        Path("relative/file.md")
    )

    assert result.allowed is False
    assert result.rule_id == "path.relative_without_workspace"
