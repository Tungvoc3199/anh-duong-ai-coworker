from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


class PathScopeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    rule_id: str
    reason: str
    normalized_path: Path | None = None


class WorkspacePathPolicy:
    """Restrict file access to configured WSL workspace roots."""

    def __init__(self, allowed_roots: tuple[Path, ...]) -> None:
        if not allowed_roots:
            raise ValueError("at least one allowed root is required")

        normalized_roots: list[Path] = []
        for root in allowed_roots:
            root_text = str(root)
            if _WINDOWS_ABSOLUTE_PATH.match(root_text):
                raise ValueError(
                    "allowed roots must use WSL paths such as /mnt/f/AIOS"
                )

            expanded_root = root.expanduser()
            if not expanded_root.is_absolute():
                raise ValueError("allowed roots must be absolute")

            normalized_roots.append(
                expanded_root.resolve(strict=False)
            )

        self.allowed_roots = tuple(normalized_roots)

    def check(
        self,
        target_path: Path,
        *,
        workspace_root: Path | None = None,
    ) -> PathScopeResult:
        target_text = str(target_path)
        if _WINDOWS_ABSOLUTE_PATH.match(target_text):
            return PathScopeResult(
                allowed=False,
                rule_id="path.windows_format",
                reason=(
                    "Use an absolute WSL path such as "
                    "/mnt/f/AIOS/project."
                ),
            )

        normalized_workspace = self._normalize_workspace(
            workspace_root
        )
        if isinstance(normalized_workspace, PathScopeResult):
            return normalized_workspace

        expanded_target = target_path.expanduser()
        if expanded_target.is_absolute():
            candidate = expanded_target
        elif normalized_workspace is not None:
            candidate = normalized_workspace / expanded_target
        else:
            return PathScopeResult(
                allowed=False,
                rule_id="path.relative_without_workspace",
                reason=(
                    "Relative target path requires an absolute "
                    "workspace root."
                ),
            )

        normalized_target = candidate.resolve(strict=False)

        # Workspace isolation is narrower than the global allowlist and must
        # be evaluated first. This catches ../ traversal to sibling projects.
        if (
            normalized_workspace is not None
            and not normalized_target.is_relative_to(
                normalized_workspace
            )
        ):
            return PathScopeResult(
                allowed=False,
                rule_id="path.outside_workspace",
                reason=(
                    "Target path resolves outside the selected workspace."
                ),
                normalized_path=normalized_target,
            )

        if not self._is_under_allowed_root(normalized_target):
            return PathScopeResult(
                allowed=False,
                rule_id="path.outside_allowlist",
                reason=(
                    "Target path resolves outside configured "
                    "allowed roots."
                ),
                normalized_path=normalized_target,
            )

        return PathScopeResult(
            allowed=True,
            rule_id="path.allowed",
            reason=(
                "Target path is inside the configured workspace scope."
            ),
            normalized_path=normalized_target,
        )

    def _normalize_workspace(
        self,
        workspace_root: Path | None,
    ) -> Path | PathScopeResult | None:
        if workspace_root is None:
            return None

        workspace_text = str(workspace_root)
        if _WINDOWS_ABSOLUTE_PATH.match(workspace_text):
            return PathScopeResult(
                allowed=False,
                rule_id="path.windows_workspace_format",
                reason="Workspace root must use an absolute WSL path.",
            )

        expanded_workspace = workspace_root.expanduser()
        if not expanded_workspace.is_absolute():
            return PathScopeResult(
                allowed=False,
                rule_id="path.relative_workspace",
                reason="Workspace root must be absolute.",
            )

        normalized_workspace = expanded_workspace.resolve(
            strict=False
        )
        if not self._is_under_allowed_root(normalized_workspace):
            return PathScopeResult(
                allowed=False,
                rule_id="path.workspace_outside_allowlist",
                reason=(
                    "Workspace root is outside configured allowed roots."
                ),
                normalized_path=normalized_workspace,
            )

        return normalized_workspace

    def _is_under_allowed_root(self, path: Path) -> bool:
        return any(
            path.is_relative_to(root)
            for root in self.allowed_roots
        )
