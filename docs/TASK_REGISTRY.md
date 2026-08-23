# Task Registry

## Mục tiêu

Task Registry theo dõi một yêu cầu công việc từ lúc tiếp nhận đến khi hoàn tất,
thất bại hoặc bị hủy.

Task luôn gắn với một Project có thật.

## Schema chính

```text
task_id
project_id
title
description
status
priority
risk_level
requested_by
source_channel
approval_required
current_step_id
result_summary
deadline
created_at
updated_at
version
```

## Status

```text
received
clarifying
planning
waiting_approval
queued
running
verifying
completed
failed
cancelled
blocked
```

## State machine

```text
received
├── clarifying
├── planning
├── blocked
└── cancelled

clarifying
├── planning
├── blocked
└── cancelled

planning
├── waiting_approval
├── queued
├── blocked
└── cancelled

waiting_approval
├── planning
├── queued
├── blocked
└── cancelled

queued
├── running
├── blocked
└── cancelled

running
├── verifying
├── failed
├── blocked
└── cancelled

verifying
├── running
├── completed
├── failed
├── blocked
└── cancelled

blocked
├── clarifying
├── planning
├── queued
├── running
└── cancelled

failed
├── planning
├── queued
└── cancelled

completed → terminal
cancelled → terminal
```

## Quy tắc bắt buộc

- Project không tồn tại thì không tạo Task.
- Mỗi transition hợp lệ tăng `version`.
- Transition sai không được thay đổi dữ liệu.
- `completed` bắt buộc có `result_summary`.
- `cancel()` idempotent khi Task đã cancelled.
- Task completed không được cancel.
- Tạo Task và đổi status đều ghi append-only audit event.
- SQLite là nguồn dữ liệu chính.

## API Python

```python
from app.tasks import (
    TaskCreate,
    TaskService,
    TaskStatus,
)

task = service.create(
    TaskCreate(
        project_id=project.id,
        title="Build Task Registry",
        description="Implement lifecycle and tests.",
    )
)

task = service.transition(task.id, TaskStatus.PLANNING)
task = service.transition(task.id, TaskStatus.QUEUED)
task = service.transition(task.id, TaskStatus.RUNNING)
task = service.transition(task.id, TaskStatus.VERIFYING)
task = service.transition(
    task.id,
    TaskStatus.COMPLETED,
    result_summary="Task Registry implemented and verified.",
)
```

## Kiểm tra

```bash
cd /mnt/f/AIOS/anh-duong-core
source .venv/bin/activate

./scripts/check_tasks.sh
pytest tests/integration/test_tasks.py -q
./scripts/test.sh
```
