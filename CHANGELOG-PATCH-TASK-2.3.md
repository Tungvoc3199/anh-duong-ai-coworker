# Task 2.3 — Append-only Audit Writer

- Thêm immutable `AuditEvent`.
- Thêm JSONL append-only writer.
- Dùng `O_APPEND` và process-local lock.
- Tạo file `0600`, state directory `0700`.
- `fsync` mặc định sau mỗi event.
- Thêm recursive secret redaction.
- Che mapping keys, bearer token, query token và provider key shapes.
- Không mutate event đầu vào.
- Thêm integrity verification.
- Thêm concurrency và security tests.
- Thêm script kiểm tra audit thực tế.
