# Append-only Audit System

## Mục tiêu

Audit ghi lại các sự kiện quan trọng theo JSONL:

- User request.
- Policy decision.
- Approval request/result.
- Skill invocation/result.
- Verification.
- Memory write.
- Project state update.

## Đường dẫn mặc định

```text
/home/thadc/.local/state/anh-duong-core/audit.jsonl
```

Không đặt audit runtime trên ổ F.

## Đặc tính

- Append-only.
- Một JSON object trên mỗi dòng.
- UTF-8 và LF.
- File mới dùng permission `0600`.
- State directory mới dùng permission `0700`.
- Redaction chạy trước serialization.
- `fsync` sau mỗi sự kiện theo mặc định.
- Thread-safe trong một process.
- Có kiểm tra integrity thủ công.

## Secret Redaction

Tự động che:

- API key.
- Bearer token.
- Password.
- Client secret.
- OpenClaw Gateway token.
- Telegram bot token.
- GitHub token.
- Slack token.
- Secret trong nested dict/list.
- Secret trong query string và assignment text.

Không thay đổi `AuditEvent` đầu vào.

## Ví dụ

```python
from pathlib import Path

from app.audit import AuditEvent, AuditWriter

writer = AuditWriter(
    Path(
        "/home/thadc/.local/state/"
        "anh-duong-core/audit.jsonl"
    )
)

writer.write(
    AuditEvent(
        event_type="policy.decision",
        payload={
            "action": "restart_service",
            "decision": "require_approval",
        },
    )
)
```

## Kiểm tra

```bash
cd /home/thadc/AIOS/anh-duong-core
source .venv/bin/activate

./scripts/check_audit.sh
pytest \
  tests/unit/test_audit_writer.py \
  tests/security/test_secret_redaction.py \
  -q

./scripts/test.sh
```
