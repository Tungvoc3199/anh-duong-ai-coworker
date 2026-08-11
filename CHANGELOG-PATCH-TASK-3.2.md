# Task 3.2 — Project Markdown Mirror

- Thêm `ProjectMirror.write_snapshot(project)`.
- Tạo `PROJECT.md`, `STATE.md`, `CHANGELOG.md`, `DECISIONS.md`.
- `PROJECT.md` và `STATE.md` cập nhật bằng temp-file, fsync và replace.
- `CHANGELOG.md` và `DECISIONS.md` không bị ghi đè sau khi tạo.
- Chuẩn hóa UTF-8 và LF.
- Fsync thư mục sau thay đổi metadata.
- Chặn slug có khả năng path traversal.
- Dọn file tạm khi ghi thất bại.
- Thêm integration tests và smoke script.
