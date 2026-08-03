from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.persona.loader import (
    PERSONA_FILE_ORDER,
    PersonaFileMissingError,
    PersonaVersionMismatchError,
    load_persona,
)


def _write_persona_file(
    root: Path,
    filename: str,
    *,
    version: str = "1.0",
    body: str = "Nội dung",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(
        f"---\nversion: \"{version}\"\n---\n\n# {filename}\n\n{body}\n",
        encoding="utf-8",
        newline="\n",
    )


def _complete_persona_dir(tmp_path: Path) -> Path:
    persona_dir = tmp_path / "persona"
    for index, filename in enumerate(PERSONA_FILE_ORDER, start=1):
        _write_persona_file(
            persona_dir,
            filename,
            body=f"Nội dung số {index}",
        )
    return persona_dir


def test_load_persona_returns_version_hash_and_language(tmp_path: Path) -> None:
    persona_dir = _complete_persona_dir(tmp_path)

    snapshot = load_persona(persona_dir)

    assert snapshot.version == "1.0"
    assert snapshot.language == "vi"
    assert snapshot.relationship == "em-anh"
    assert len(snapshot.content_hash) == 64
    assert snapshot.file_order == PERSONA_FILE_ORDER


def test_load_persona_uses_canonical_file_order(tmp_path: Path) -> None:
    persona_dir = _complete_persona_dir(tmp_path)

    snapshot = load_persona(persona_dir)

    positions = [
        snapshot.combined_content.index(f"<!-- source: {filename} -->")
        for filename in PERSONA_FILE_ORDER
    ]
    assert positions == sorted(positions)


def test_content_hash_matches_canonical_content(tmp_path: Path) -> None:
    persona_dir = _complete_persona_dir(tmp_path)

    snapshot = load_persona(persona_dir)

    expected = hashlib.sha256(
        snapshot.combined_content.encode("utf-8")
    ).hexdigest()
    assert snapshot.content_hash == expected


def test_missing_persona_file_is_rejected(tmp_path: Path) -> None:
    persona_dir = _complete_persona_dir(tmp_path)
    (persona_dir / "SOUL.md").unlink()

    with pytest.raises(PersonaFileMissingError, match="SOUL.md"):
        load_persona(persona_dir)


def test_inconsistent_versions_are_rejected(tmp_path: Path) -> None:
    persona_dir = _complete_persona_dir(tmp_path)
    _write_persona_file(
        persona_dir,
        "WORK_STYLE.md",
        version="1.1",
        body="Khác phiên bản",
    )

    with pytest.raises(PersonaVersionMismatchError, match="WORK_STYLE.md"):
        load_persona(persona_dir)


def test_crlf_and_lf_generate_same_hash(tmp_path: Path) -> None:
    lf_dir = _complete_persona_dir(tmp_path / "lf")
    crlf_dir = _complete_persona_dir(tmp_path / "crlf")

    for filename in PERSONA_FILE_ORDER:
        path = crlf_dir / filename
        content = path.read_text(encoding="utf-8")
        path.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))

    assert load_persona(lf_dir).content_hash == load_persona(crlf_dir).content_hash
