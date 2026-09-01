from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

from ade_os import core  # noqa: E402
from agent import pretool_guard  # noqa: E402


def test_current_worktree_root_is_allowed_by_root_policy() -> None:
    lane = Path('/home/thadc/AIOS/worktrees/example-lane')
    assert core.core_worktree_root_for(lane) == Path('/home/thadc/AIOS/worktrees')


def test_legacy_worktree_root_remains_allowed_by_root_policy() -> None:
    lane = Path('/home/thadc/AIOS/anh-duong-core.worktrees/example-lane')
    assert core.core_worktree_root_for(lane) == Path('/home/thadc/AIOS/anh-duong-core.worktrees')


def test_unapproved_worktree_root_is_rejected_by_root_policy() -> None:
    lane = Path('/home/thadc/AIOS/arbitrary/example-lane')
    assert core.core_worktree_root_for(lane) is None


def test_repo_relative_handles_current_and_legacy_roots() -> None:
    current = '/home/thadc/AIOS/worktrees/lane/scripts/ade_os.py'
    legacy = '/home/thadc/AIOS/anh-duong-core.worktrees/lane/scripts/ade_os.py'
    assert pretool_guard.repo_relative(current) == 'scripts/ade_os.py'
    assert pretool_guard.repo_relative(legacy) == 'scripts/ade_os.py'
