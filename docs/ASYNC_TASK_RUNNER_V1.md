# Async Task Runner v1

Async Task Runner nhận yêu cầu qua internal API, lưu bền vững trong SQLite,
thực thi nền qua OpenClaw HTTP Gateway, rồi gửi thông báo cuối qua HTTP
`/tools/invoke`. Runtime không có CLI fallback.

## Điều kiện triển khai

- Python 3.12.
- Migration `0003` phải được áp dụng bởi người vận hành trước khi bật worker.
- OpenClaw Gateway đã phục vụ `POST /v1/responses` và `POST /tools/invoke`.
- Internal API token và OpenClaw Gateway token được cấp qua biến môi trường.
- Workspace roots dùng JSON array, ví dụ `["/mnt/f/AIOS"]`.

Các biến chính:

```text
ANH_DUONG_INTERNAL_API_TOKEN=<internal bearer token>
ANH_DUONG_OPENCLAW_AUTH_TOKEN=<gateway bearer token>
ANH_DUONG_OPENCLAW_BASE_URL=http://127.0.0.1:18789
ANH_DUONG_OPENCLAW_EXECUTION_PATH=/v1/responses
ANH_DUONG_OPENCLAW_NOTIFICATION_PATH=/tools/invoke
ANH_DUONG_OPENCLAW_TIMEOUT_SECONDS=600
ANH_DUONG_ASYNC_WORKER_ENABLED=true
ANH_DUONG_ASYNC_WORKER_WORKSPACE_ROOTS=["/mnt/f/AIOS"]
```

Nếu `ANH_DUONG_INTERNAL_API_TOKEN` thiếu, mọi endpoint async trả `503`.
Token sai hoặc thiếu header trả `401`. `POST /api/async-tasks` còn kiểm tra
`app.state.accepting_async_tasks`; state thiếu/false trong startup hoặc shutdown
trả `503` trước khi tạo Task/Run.

## API

Tất cả endpoint yêu cầu:

```text
Authorization: Bearer <internal token>
```

Endpoint:

```text
POST /api/async-tasks
GET /api/async-tasks/{run_id}
GET /api/async-tasks?status=pending&task_id=task_...
POST /api/async-tasks/{run_id}/retry
POST /api/async-tasks/{run_id}/cancel
```

`POST` trả `202` sau khi commit Task/Run, không chờ OpenClaw. Với explicit
`idempotency_key`, Core lấy SQLite `BEGIN IMMEDIATE` trước lookup đầu tiên.
Hai request đồng thời vì vậy trả cùng Task/Run và không tạo orphan Task; unique
constraint trên Run vẫn là invariant cuối.

List filter `task_id` được áp dụng trong SQL trước `limit`/`offset`. Manual
retry chỉ áp dụng cho run `failed` hoặc `blocked` và policy được đánh giá lại.

## Cancel safety v1

- `pending`, `retry_wait`: cancel ngay bằng conditional SQL update.
- `claimed`, `running`, `verifying`: trả `409`; v1 không hứa interrupt một
  OpenClaw HTTP request đang chạy.
- `completed`: trả `409`.
- `cancelled`: trả idempotent, không ghi event cancel thứ hai.

API lấy SQLite write lock trước khi đọc trạng thái cancel và repository chỉ
update khi trạng thái DB vẫn là `pending`/`retry_wait`. Stale cached row không
thể ghi đè một run đã chuyển sang active, nên Core không báo cancelled trong
khi OpenClaw vẫn có thể tạo side effect.

## Append-only audit

Async Run và notification ghi riêng vào JSONL append-only:

```text
async_run.created
async_run.claimed
async_run.retry_scheduled
async_run.completed
async_run.failed
async_run.blocked
async_run.recovered
async_run.cancelled
async_notification.sent
async_notification.failed
```

Mỗi HTTP notification failure có một `async_notification.failed`, kể cả khi
còn retry. Payload chỉ chứa metadata bounded: run/task/project, status,
attempt/version, error đã redact và SHA256 của idempotency key. Không chép
`goal`, raw request, raw idempotency key, authorization header hay token vào
audit payload. `SecretRedactor` tiếp tục lọc recursive trước khi append.

## State, retry và recovery

- Task: `received → planning → queued → running → verifying → terminal`.
- Execution run: tối đa ba attempt; transient retry sau 5 giây rồi 30 giây.
- Uncertain side effect chuyển `blocked`, không retry tự động.
- Startup recovery chỉ requeue Risk 0; Risk 1 cần idempotency key và không có
  uncertainty marker. Trường hợp khác chuyển `blocked`.
- Notification retry độc lập tối đa năm lần. Notification lỗi không thay đổi
  Task đã `completed`.

Mỗi background operation mở session riêng. Worker commit lease và trạng thái
`running` trước khi `await` HTTP, nên không giữ SQL transaction trong lúc chờ
Gateway.

## Verification an toàn

E2E dùng HTTP mock cho cả `/v1/responses` và `/tools/invoke`; không gọi
OpenClaw/Telegram thật. Migration round-trip chỉ dùng database tạm. Phiên
correction không migrate runtime DB, restart service, sửa OpenClaw config hay
deploy.

## Smoke read-only

Script chỉ gọi health và list API; không tạo task, không gọi OpenClaw và không
gửi Telegram:

```bash
ANH_DUONG_INTERNAL_API_TOKEN='<token>' \
  .venv/bin/python scripts/smoke_async_task_runner.py \
  --base-url http://127.0.0.1:8790
```

## Cài đặt và rollback

Sau khi backup database runtime và trong maintenance window:

```bash
.venv/bin/alembic upgrade 0003
.venv/bin/python -m pytest -q
```

Việc restart service và thay OpenClaw config không nằm trong gói này.

Rollback code bằng cách khôi phục overlay trước đó. Chỉ downgrade schema khi
worker đã dừng và database đã backup:

```bash
.venv/bin/alembic downgrade 0002
```

Downgrade xóa bảng `async_task_runs`, vì vậy mọi run chưa bàn giao sẽ mất.
