from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.audit.models import AuditEvent, AuditIntegrityResult
from app.audit.redaction import SecretRedactor


class AuditWriter:
    """Append-only JSONL writer with redaction and integrity checks."""

    def __init__(
        self,
        path: Path,
        *,
        redactor: SecretRedactor | None = None,
        fsync: bool = True,
    ) -> None:
        self.path = Path(path).expanduser()
        self.redactor = redactor or SecretRedactor()
        self.fsync = fsync
        self._lock = threading.Lock()

    def write(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        raw_record = event.model_dump(mode="json")
        redacted_record = self.redactor.redact(raw_record)
        encoded = self._encode_line(redacted_record)

        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        with self._lock:
            descriptor = os.open(self.path, flags, 0o600)
            try:
                self._write_all(descriptor, encoded)
                if self.fsync:
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def verify_integrity(self) -> AuditIntegrityResult:
        if not self.path.exists():
            return AuditIntegrityResult(
                valid=True,
                line_count=0,
            )

        line_count = 0
        try:
            with self.path.open(
                "r",
                encoding="utf-8",
                newline="",
            ) as handle:
                for line_number, raw_line in enumerate(
                    handle,
                    start=1,
                ):
                    line_count = line_number
                    if not raw_line.endswith("\n"):
                        return AuditIntegrityResult(
                            valid=False,
                            line_count=line_count,
                            invalid_line_number=line_number,
                            error="line is not newline terminated",
                        )

                    try:
                        parsed = json.loads(raw_line)
                    except json.JSONDecodeError as exc:
                        return AuditIntegrityResult(
                            valid=False,
                            line_count=line_count,
                            invalid_line_number=line_number,
                            error=str(exc),
                        )

                    if not isinstance(parsed, dict):
                        return AuditIntegrityResult(
                            valid=False,
                            line_count=line_count,
                            invalid_line_number=line_number,
                            error="audit record must be a JSON object",
                        )
        except UnicodeDecodeError as exc:
            return AuditIntegrityResult(
                valid=False,
                line_count=line_count,
                invalid_line_number=max(line_count, 1),
                error=str(exc),
            )

        return AuditIntegrityResult(
            valid=True,
            line_count=line_count,
        )

    @staticmethod
    def _write_all(descriptor: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise OSError("audit write made no progress")
            offset += written

    @staticmethod
    def _encode_line(record: Any) -> bytes:
        serialized = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return f"{serialized}\n".encode()
