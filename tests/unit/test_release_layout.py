from pathlib import Path


RELEASE_ROOT = "/home/thadc/AIOS/releases/anh-duong-core"
ACTIVE_RELEASE = f"{RELEASE_ROOT}/current"
HISTORICAL_SOURCE = "/home/thadc/AIOS/anh-duong-core"


def test_systemd_unit_uses_active_release_layout() -> None:
    unit = Path("systemd/anh-duong-core.service").read_text(encoding="utf-8")

    assert f"WorkingDirectory={ACTIVE_RELEASE}" in unit
    assert f"ExecStart={ACTIVE_RELEASE}/.venv/bin/uvicorn app.main:app" in unit
    assert HISTORICAL_SOURCE not in unit


def test_install_script_requires_active_release_and_never_historical_source() -> None:
    script = Path("scripts/install_systemd.sh").read_text(encoding="utf-8")

    assert f'RELEASE_ROOT="{RELEASE_ROOT}"' in script
    assert 'ACTIVE_RELEASE="${RELEASE_ROOT}/current"' in script
    assert 'UNIT_SOURCE="${ACTIVE_RELEASE}/systemd/anh-duong-core.service"' in script
    assert 'PROJECT_ROOT="/home/thadc/AIOS/anh-duong-core"' not in script
    assert 'sudo systemctl enable --now' not in script


def test_repository_operator_scripts_derive_their_project_root() -> None:
    scripts = (
        "check_audit.sh",
        "check_memory_fts.sh",
        "check_persona.sh",
        "check_policy.sh",
        "check_project_mirror.sh",
        "check_projects.sh",
        "check_tasks.sh",
        "dev.sh",
    )
    expected = 'PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"'

    for name in scripts:
        script = Path("scripts", name).read_text(encoding="utf-8")
        assert expected in script, name
        assert 'PROJECT_ROOT="/home/thadc/AIOS/anh-duong-core"' not in script, name


def test_runbook_distinguishes_historical_and_release_paths() -> None:
    runbook = Path("docs/RUNBOOK_SYSTEMD.md").read_text(encoding="utf-8")

    assert f"HISTORICAL_SOURCE={HISTORICAL_SOURCE}" in runbook
    assert f"RELEASE_ROOT={RELEASE_ROOT}" in runbook
    assert f"ACTIVE_RELEASE={ACTIVE_RELEASE}" in runbook
    assert "DATA_MIRROR=/mnt/f/AIOS/anh-duong-data" in runbook
    assert "first-migration preimage" in runbook
    assert "systemctl show" in runbook


def test_canonical_hooks_use_the_stable_active_release() -> None:
    for name in ("audit.json", "safety.json", "validation.json"):
        hook = Path(".github/hooks", name).read_text(encoding="utf-8")
        assert ACTIVE_RELEASE in hook, name
        assert HISTORICAL_SOURCE not in hook, name


def test_setup_does_not_upgrade_pip_implicitly() -> None:
    setup = Path("scripts/setup.sh").read_text(encoding="utf-8")

    assert "pip install --upgrade pip" not in setup
