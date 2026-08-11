from pathlib import Path


def test_internal_auth_uses_constant_time_comparison() -> None:
    source = Path("app/api/async_tasks.py").read_text(
        encoding="utf-8"
    )

    assert "compare_digest" in source
    assert "Internal API authentication is not configured." in source


def test_runtime_openclaw_modules_have_no_cli_fallback() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("app/openclaw").glob("*.py")
    )
    forbidden = (
        "subprocess",
        "os.system",
        "docker compose",
        "node dist/index.js",
        "shell=True",
    )

    assert not any(item in source for item in forbidden)
