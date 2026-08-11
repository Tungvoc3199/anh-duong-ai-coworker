# Project Registry & State Machine

## Trạng thái

```text
idea
planned
active
blocked
paused
completed
archived
```

## Transition hợp lệ

```text
idea      → planned | archived
planned   → active | paused | archived
active    → blocked | paused | completed | archived
blocked   → active | paused | archived
paused    → active | archived
completed → archived
archived  → terminal
```

Mỗi transition hợp lệ:

- Tăng `version`.
- Cập nhật `updated_at`.
- Cập nhật `last_activity_at`.
- Ghi append-only audit event.

## Kiểm tra

```bash
cd /mnt/f/AIOS/anh-duong-core
source .venv/bin/activate

./scripts/check_projects.sh
pytest tests/integration/test_projects.py -q
./scripts/test.sh
```
