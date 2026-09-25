from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_TRUTH = "/usr/local/libexec/anh-duong/runtime-truth"
OLD_DATA_ROOT = "/home/thadc/AIOS/anh-duong-data"
DATA_ROOT = "/mnt/f/AIOS/anh-duong-data"


def test_agent_entrypoints_share_canonical_runtime_contract() -> None:
    entrypoints = (
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "GEMINI.md",
        ROOT / ".github" / "copilot-instructions.md",
        ROOT / ".github" / "instructions" / "runtime-truth.instructions.md",
    )
    for path in entrypoints:
        text = path.read_text(encoding="utf-8")
        assert "AGENT_RUNTIME_CONTRACT.md" in text, path
        assert RUNTIME_TRUTH in text, path


def test_runtime_truth_probe_has_no_hardcoded_core_port() -> None:
    text = (ROOT / "scripts" / "runtime_truth.sh").read_text(encoding="utf-8")
    assert "systemctl show" in text
    assert "/proc/${main_pid}/cmdline" in text
    assert "CORE_PORT_SOURCE" in text
    assert "OPENCLAW_HEALTH" in text
    assert "--port" in text
    assert "127.0.0.1:8790" not in text
    assert "127.0.0.1:8792" not in text


def test_current_docs_and_setup_use_migrated_data_root() -> None:
    current_files = (
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / ".env.example",
        ROOT / "app" / "config.py",
        ROOT / "scripts" / "setup.sh",
        ROOT / "docs" / "PROJECT_MARKDOWN_MIRROR.md",
        ROOT / "docs" / "AGENT_RUNTIME_CONTRACT.md",
    )
    for path in current_files:
        text = path.read_text(encoding="utf-8")
        assert OLD_DATA_ROOT not in text, path
        assert DATA_ROOT in text, path


def test_systemd_template_uses_release_pointer_and_configurable_port() -> None:
    text = (ROOT / "systemd" / "anh-duong-core.service").read_text(encoding="utf-8")
    assert "WorkingDirectory=/home/thadc/AIOS/releases/anh-duong-core/current" in text
    assert (
        "ExecStart=/home/thadc/AIOS/releases/anh-duong-core/current/.venv/bin/uvicorn"
        in text
    )
    assert "--port ${ANH_DUONG_CORE_PORT}" in text
    assert "WorkingDirectory=/home/thadc/AIOS/anh-duong-core" not in text


def test_worker_has_no_self_http_port_dependency() -> None:
    text = (ROOT / "app" / "async_tasks" / "worker.py").read_text(encoding="utf-8")
    assert "127.0.0.1:8790" not in text
    assert "127.0.0.1:8792" not in text
    assert "core_internal_asgi_get" in text


def test_portability_probe_verifies_current_worktree_import() -> None:
    text = (ROOT / "scripts" / "verify_worktree_portability.sh").read_text(
        encoding="utf-8"
    )
    assert 'source "${SCRIPT_DIR}/lib/project_env.sh"' in text
    assert "WORKTREE_IMPORT=PASS" in text
    assert 'case "${app_file}" in' in text
