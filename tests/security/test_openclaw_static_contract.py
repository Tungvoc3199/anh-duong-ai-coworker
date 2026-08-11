from pathlib import Path


def test_runtime_executor_has_no_cli_fallback() -> None:
    source = Path("app/openclaw/executor.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "subprocess",
        "os.system",
        "docker compose",
        "node dist/index.js",
        "shell=True",
    )

    assert not any(item in source for item in forbidden)
