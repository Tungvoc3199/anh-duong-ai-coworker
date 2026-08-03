from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

from app.projects.models import Project

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class InvalidProjectMirrorSlug(ValueError):
    """Raised when a project slug could escape the mirror root."""


class ProjectMirror:
    """Write human-readable project snapshots safely and atomically."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)

    def write_snapshot(self, project: Project) -> Path:
        self._validate_slug(project.slug)

        project_dir = self.root / project.slug
        project_dir.mkdir(parents=True, exist_ok=True)

        self._atomic_replace(
            project_dir / "PROJECT.md",
            self._render_project(project),
        )
        self._atomic_replace(
            project_dir / "STATE.md",
            self._render_state(project),
        )
        self._create_if_missing(
            project_dir / "CHANGELOG.md",
            self._render_changelog(project),
        )
        self._create_if_missing(
            project_dir / "DECISIONS.md",
            self._render_decisions(project),
        )

        self._fsync_directory(project_dir)
        return project_dir

    @staticmethod
    def _validate_slug(slug: str) -> None:
        if _SLUG_PATTERN.fullmatch(slug) is None:
            raise InvalidProjectMirrorSlug(
                f"Invalid project slug for mirror path: {slug}"
            )

    def _atomic_replace(self, target: Path, content: str) -> None:
        temporary = target.parent / (
            f".{target.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                handle.write(self._normalize(content))
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temporary, target)
            self._fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _create_if_missing(self, target: Path, content: str) -> None:
        if target.exists():
            return

        temporary = target.parent / (
            f".{target.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                handle.write(self._normalize(content))
                handle.flush()
                os.fsync(handle.fileno())

            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
            self._fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _normalize(content: str) -> str:
        return (
            content.replace("\r\n", "\n")
            .replace("\r", "\n")
            .rstrip()
            + "\n"
        )

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY

        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _display(value: object | None) -> str:
        if value is None or value == "":
            return "Chưa thiết lập"
        return str(value)

    @classmethod
    def _render_project(cls, project: Project) -> str:
        constraints = (
            "\n".join(
                f"- {constraint}"
                for constraint in project.constraints
            )
            or "- Không có"
        )

        return f"""---
project_id: "{project.id}"
slug: "{project.slug}"
status: "{project.status.value}"
priority: "{project.priority.value}"
version: {project.version}
updated_at: "{project.updated_at.isoformat()}"
---

# {project.name}

## Tổng quan

- **Project ID:** `{project.id}`
- **Slug:** `{project.slug}`
- **Owner:** {project.owner}
- **Priority:** **{project.priority.value}**
- **Current phase:** {cls._display(project.current_phase)}

## Mô tả

{cls._display(project.summary)}

## Đường dẫn

- **Windows:** `{cls._display(project.path_windows)}`
- **WSL:** `{cls._display(project.path_wsl)}`
- **Repository:** {cls._display(project.repo_url)}

## Ràng buộc

{constraints}
"""

    @classmethod
    def _render_state(cls, project: Project) -> str:
        return f"""# State — {project.name}

- **Status:** **{project.status.value}**
- **Priority:** **{project.priority.value}**
- **Version:** `{project.version}`
- **Current phase:** {cls._display(project.current_phase)}
- **Next action:** {cls._display(project.next_action)}
- **Last activity:** {cls._display(project.last_activity_at)}
- **Updated at:** {project.updated_at.isoformat()}
"""

    @staticmethod
    def _render_changelog(project: Project) -> str:
        return f"""# Changelog — {project.name}

> File do con người duy trì. Project Mirror chỉ tạo khi chưa tồn tại.

## Unreleased

- Chưa có thay đổi được ghi nhận.
"""

    @staticmethod
    def _render_decisions(project: Project) -> str:
        return f"""# Decisions — {project.name}

> File do con người duy trì. Project Mirror chỉ tạo khi chưa tồn tại.

| Date | Decision | Reason | Status |
|---|---|---|---|
| | | | |
"""
