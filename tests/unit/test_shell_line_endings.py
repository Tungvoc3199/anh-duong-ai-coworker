from pathlib import Path


def test_all_shell_scripts_use_lf_only() -> None:
    scripts = list(Path("scripts").glob("*.sh"))
    assert scripts
    for script in scripts:
        content = script.read_bytes()
        assert b"\r\n" not in content, f"{script} contains CRLF"
        assert content.startswith(b"#!/usr/bin/env bash\n")
