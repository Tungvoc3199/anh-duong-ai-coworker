from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.config import Settings
from app.main import create_app

TOKEN = "attachment-api-token"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'unused.db'}",
        audit_path=tmp_path / "attachment-audit.jsonl",
        internal_api_token=TOKEN,
        async_worker_enabled=False,
    )


def test_prepare_accepts_document_attachment_without_forcing_workflow(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings=settings, engine=migrated_engine)

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/requests/prepare",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "text": "File đây nhé",
                "request_id": "req-attachment-api",
                "channel": "telegram",
                "actor": "telegram:test",
                "source_message_id": "42",
                "attachments": [
                    {
                        "index": 0,
                        "kind": "document",
                        "content_type": (
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                        "filename": "a.docx",
                        "local_ref": "/tmp/openclaw/a.docx",
                        "provider_ref": "media://telegram/a",
                        "staged": True,
                        "source_message_id": "42",
                    }
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "req-attachment-api"
    assert payload["route_decision"]["route"] == "direct"
    assert payload["route_decision"]["rule_id"] == "routing.direct.attachment_context"
    assert payload["execution_required"] is False
    rendered = payload["context"]["rendered_context"]
    assert "Attachments:" in rendered
    assert "kind=document" in rendered
    assert "filename=a.docx" in rendered
    assert "attachment:0" in payload["provenance"]["context_source_refs"]

    records = [
        json.loads(line)
        for line in settings.audit_path.read_text(encoding="utf-8").splitlines()
    ]
    audit_payload = records[-1]["payload"]
    assert audit_payload["attachment_count"] == 1
    audit_json = json.dumps(audit_payload, ensure_ascii=False)
    assert "a.docx" not in audit_json
    assert "/tmp/openclaw/a.docx" not in audit_json
