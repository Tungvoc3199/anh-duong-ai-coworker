from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.persona.models import PersonaSnapshot

PERSONA_FILE_ORDER: tuple[str, ...] = (
    "IDENTITY.md",
    "SOUL.md",
    "USER.md",
    "WORK_STYLE.md",
)

_FRONTMATTER_PATTERN = re.compile(
    r"\A---\n(?P<frontmatter>.*?)\n---\n?(?P<body>.*)\Z",
    re.DOTALL,
)
_VERSION_PATTERN = re.compile(
    r'(?m)^version:\s*["\']?(?P<version>[^"\'\s]+)["\']?\s*$'
)


class PersonaLoadError(RuntimeError):
    """Base error for persona loading failures."""


class PersonaFileMissingError(PersonaLoadError):
    """Raised when a required persona file is absent."""


class PersonaFrontmatterError(PersonaLoadError):
    """Raised when frontmatter or version metadata is invalid."""


class PersonaVersionMismatchError(PersonaLoadError):
    """Raised when required persona files do not share one version."""


def _normalize_newlines(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def _parse_persona_file(path: Path) -> tuple[str, str]:
    content = _normalize_newlines(path.read_text(encoding="utf-8")).strip() + "\n"
    match = _FRONTMATTER_PATTERN.fullmatch(content)
    if match is None:
        raise PersonaFrontmatterError(
            f"{path.name} must start with YAML frontmatter"
        )

    version_match = _VERSION_PATTERN.search(match.group("frontmatter"))
    if version_match is None:
        raise PersonaFrontmatterError(
            f"{path.name} frontmatter must define version"
        )

    return version_match.group("version"), content


def load_persona(root: Path) -> PersonaSnapshot:
    """Load, validate and hash the canonical Ánh Dương persona files."""

    persona_root = Path(root)
    files: dict[str, str] = {}
    versions: dict[str, str] = {}

    for filename in PERSONA_FILE_ORDER:
        path = persona_root / filename
        if not path.is_file():
            raise PersonaFileMissingError(
                f"Required persona file is missing: {filename}"
            )

        version, content = _parse_persona_file(path)
        versions[filename] = version
        files[filename] = content

    expected_version = versions[PERSONA_FILE_ORDER[0]]
    mismatches = [
        f"{filename}={version}"
        for filename, version in versions.items()
        if version != expected_version
    ]
    if mismatches:
        details = ", ".join(mismatches)
        raise PersonaVersionMismatchError(
            f"Persona files must share version {expected_version}; mismatch: {details}"
        )

    combined_sections = [
        f"<!-- source: {filename} -->\n{files[filename].rstrip()}\n"
        for filename in PERSONA_FILE_ORDER
    ]
    combined_content = "\n".join(combined_sections)
    content_hash = hashlib.sha256(
        combined_content.encode("utf-8")
    ).hexdigest()

    return PersonaSnapshot(
        version=expected_version,
        language="vi",
        relationship="em-anh",
        tone="direct",
        content_hash=content_hash,
        file_order=PERSONA_FILE_ORDER,
        files=files,
        combined_content=combined_content,
    )
