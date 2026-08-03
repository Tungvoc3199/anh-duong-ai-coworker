# Task 3.3 — Task Registry

- Thêm `TaskStatus`, `TaskPriority`, `TaskCreate` và immutable `Task`.
- Thêm SQLAlchemy `TaskRepository`.
- Thêm `TaskService.create`, `get`, `list`, `transition`, `cancel`.
- Task bắt buộc gắn với Project tồn tại.
- Thêm deterministic state machine cho 11 trạng thái.
- `completed` bắt buộc có `result_summary`.
- `cancel()` idempotent khi Task đã cancelled.
- Completed và cancelled là terminal.
- Failed Task có thể quay lại planning hoặc queued.
- Mỗi transition tăng `version` và cập nhật `updated_at`.
- Ghi audit khi tạo và đổi trạng thái.
- Chuẩn hóa SQLite datetime về UTC.
- Thêm integration tests và smoke script.
