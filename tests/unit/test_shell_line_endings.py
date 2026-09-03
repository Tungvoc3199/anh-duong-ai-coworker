from pathlib import Path


def test_all_shell_scripts_use_lf_only() -> None:
    scripts = list(Path("scripts").rglob("*.sh"))
    assert scripts
    for script in scripts:
        content = script.read_bytes()
        assert b"\r\n" not in content, f"{script} contains CRLF"
        if script.name in {"coding_preflight.sh", "install_coding_preflight_controller.sh"}:
            assert content.startswith(b"#!/bin/bash -p\n")
        else:
            assert content.startswith(b"#!/usr/bin/env bash\n")
