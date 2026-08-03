from pathlib import Path

from app.persona.loader import PERSONA_FILE_ORDER, load_persona


def test_packaged_persona_files_are_loadable() -> None:
    root = Path("data/persona")
    snapshot = load_persona(root)

    assert snapshot.version == "1.0"
    assert snapshot.file_order == PERSONA_FILE_ORDER
    assert "Ánh Dương" in snapshot.combined_content
    assert "không tự phê duyệt" in snapshot.combined_content.lower()
