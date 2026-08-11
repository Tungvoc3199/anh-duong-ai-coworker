from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.projects.mirror import (
    InvalidProjectMirrorSlug,
    ProjectMirror,
)
from app.projects.models import (
    Project,
    ProjectPriority,
    ProjectStatus,
)


def _project(
    *,
    status: ProjectStatus = ProjectStatus.ACTIVE,
    version: int = 3,
    slug: str = "anh-duong-core",
) -> Project:
    now = datetime(2026, 7, 24, 10, 30, tzinfo=UTC)
    return Project(
        id="proj_1234567890abcdef",
        name="Ánh Dương Core",
        slug=slug,
        status=status,
        priority=ProjectPriority.HIGH,
        path_windows=r"F:\AIOS\anh-duong-core",
        path_wsl="/mnt/f/AIOS/anh-duong-core",
        repo_url="https://example.test/anh-duong-core",
        current_phase="Phase 3",
        owner="user",
        summary="Bộ não điều phối của AIOS.",
        next_action="Build Project Markdown Mirror.",
        constraints=("local-first", "approval-required"),
        created_at=now,
        updated_at=now,
        last_activity_at=now,
        version=version,
    )


def test_project_mirror_writes_all_readable_files(
    tmp_path: Path,
) -> None:
    project = _project()

    project_dir = ProjectMirror(tmp_path).write_snapshot(project)

    assert project_dir == tmp_path / project.slug
    assert {
        path.name for path in project_dir.iterdir()
    } == {
        "CHANGELOG.md",
        "DECISIONS.md",
        "PROJECT.md",
        "STATE.md",
    }
    assert "Ánh Dương Core" in (
        project_dir / "PROJECT.md"
    ).read_text(encoding="utf-8")
    assert "**active**" in (
        project_dir / "STATE.md"
    ).read_text(encoding="utf-8")


def test_snapshot_contains_project_identity_and_paths(
    tmp_path: Path,
) -> None:
    project = _project()

    project_dir = ProjectMirror(tmp_path).write_snapshot(project)
    content = (project_dir / "PROJECT.md").read_text(
        encoding="utf-8"
    )

    assert "proj_1234567890abcdef" in content
    assert "anh-duong-core" in content
    assert r"F:\AIOS\anh-duong-core" in content
    assert "/mnt/f/AIOS/anh-duong-core" in content
    assert "local-first" in content


def test_rewriting_snapshot_updates_generated_state(
    tmp_path: Path,
) -> None:
    mirror = ProjectMirror(tmp_path)
    project = _project(
        status=ProjectStatus.ACTIVE,
        version=3,
    )
    mirror.write_snapshot(project)

    updated = project.model_copy(
        update={
            "status": ProjectStatus.BLOCKED,
            "version": 4,
            "next_action": "Resolve OpenClaw connectivity.",
        }
    )
    mirror.write_snapshot(updated)

    state = (
        tmp_path / project.slug / "STATE.md"
    ).read_text(encoding="utf-8")
    assert "**blocked**" in state
    assert "`4`" in state
    assert "Resolve OpenClaw connectivity." in state
    assert "**active**" not in state


def test_human_maintained_files_are_not_overwritten(
    tmp_path: Path,
) -> None:
    mirror = ProjectMirror(tmp_path)
    project = _project()
    project_dir = mirror.write_snapshot(project)

    changelog = project_dir / "CHANGELOG.md"
    decisions = project_dir / "DECISIONS.md"
    changelog.write_text(
        "# Changelog\n\n- Manual entry\n",
        encoding="utf-8",
        newline="\n",
    )
    decisions.write_text(
        "# Decisions\n\n- Keep HTTP-only runtime\n",
        encoding="utf-8",
        newline="\n",
    )

    mirror.write_snapshot(
        project.model_copy(update={"version": 4})
    )

    assert "Manual entry" in changelog.read_text(
        encoding="utf-8"
    )
    assert "Keep HTTP-only runtime" in decisions.read_text(
        encoding="utf-8"
    )


def test_snapshot_files_use_lf_only(tmp_path: Path) -> None:
    project_dir = ProjectMirror(tmp_path).write_snapshot(
        _project()
    )

    for path in project_dir.glob("*.md"):
        assert b"\r" not in path.read_bytes()


def test_successful_write_leaves_no_temp_files(
    tmp_path: Path,
) -> None:
    project_dir = ProjectMirror(tmp_path).write_snapshot(
        _project()
    )

    assert not list(project_dir.glob(".*.tmp"))


def test_atomic_replace_failure_cleans_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mirror = ProjectMirror(tmp_path)
    project = _project()

    def fail_replace(
        source: str | os.PathLike[str],
        target: str | os.PathLike[str],
    ) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        mirror.write_snapshot(project)

    project_dir = tmp_path / project.slug
    assert not list(project_dir.glob(".*.tmp"))


def test_invalid_slug_cannot_escape_mirror_root(
    tmp_path: Path,
) -> None:
    project = _project(slug="../outside")

    with pytest.raises(
        InvalidProjectMirrorSlug,
        match="Invalid project slug",
    ):
        ProjectMirror(tmp_path).write_snapshot(project)

    assert not (tmp_path.parent / "outside").exists()
