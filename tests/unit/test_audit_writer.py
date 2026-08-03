from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.audit.models import AuditEvent
from app.audit.writer import AuditWriter


def _read_json_lines(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_writer_appends_json_lines_in_order(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    writer = AuditWriter(audit_path)

    writer.write(
        AuditEvent(
            event_type="task.received",
            payload={"task_id": "task_1"},
        )
    )
    writer.write(
        AuditEvent(
            event_type="task.completed",
            payload={"task_id": "task_1"},
        )
    )

    records = _read_json_lines(audit_path)

    assert [record["event_type"] for record in records] == [
        "task.received",
        "task.completed",
    ]
    assert all(
        str(record["event_id"]).startswith("aud_")
        for record in records
    )


def test_writer_creates_parent_directory(tmp_path: Path) -> None:
    audit_path = tmp_path / "nested" / "state" / "audit.jsonl"

    AuditWriter(audit_path).write(
        AuditEvent(event_type="system.started")
    )

    assert audit_path.is_file()


def test_writer_redacts_nested_secrets_without_mutating_event(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.jsonl"
    event = AuditEvent(
        event_type="provider.request",
        payload={
            "authorization": "Bearer top-secret-token",
            "nested": {
                "password": "correct-horse-battery-staple",
                "safe": "keep-me",
            },
        },
    )

    AuditWriter(audit_path).write(event)
    record = _read_json_lines(audit_path)[0]
    payload = record["payload"]

    assert payload["authorization"] == "[REDACTED]"
    assert payload["nested"]["password"] == "[REDACTED]"
    assert payload["nested"]["safe"] == "keep-me"
    assert event.payload["authorization"] == "Bearer top-secret-token"


def test_writer_output_is_one_valid_json_object_per_line(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.jsonl"
    writer = AuditWriter(audit_path)

    writer.write(
        AuditEvent(
            event_type="message.received",
            payload={"text": "line one\nline two"},
        )
    )

    raw_lines = audit_path.read_text(encoding="utf-8").splitlines()

    assert len(raw_lines) == 1
    assert json.loads(raw_lines[0])["payload"]["text"] == (
        "line one\nline two"
    )


def test_concurrent_writes_do_not_corrupt_jsonl(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.jsonl"
    writer = AuditWriter(audit_path)

    def write_event(index: int) -> None:
        writer.write(
            AuditEvent(
                event_type="concurrency.probe",
                payload={"index": index},
            )
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(write_event, range(100)))

    records = _read_json_lines(audit_path)

    assert len(records) == 100
    assert {
        record["payload"]["index"]
        for record in records
    } == set(range(100))


def test_verify_integrity_accepts_clean_log(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    writer = AuditWriter(audit_path)
    writer.write(AuditEvent(event_type="one"))
    writer.write(AuditEvent(event_type="two"))

    result = writer.verify_integrity()

    assert result.valid is True
    assert result.line_count == 2
    assert result.invalid_line_number is None


def test_verify_integrity_reports_first_invalid_line(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.jsonl"
    writer = AuditWriter(audit_path)
    writer.write(AuditEvent(event_type="one"))

    with audit_path.open("ab") as handle:
        handle.write(b"{broken-json}\n")

    result = writer.verify_integrity()

    assert result.valid is False
    assert result.line_count == 2
    assert result.invalid_line_number == 2
