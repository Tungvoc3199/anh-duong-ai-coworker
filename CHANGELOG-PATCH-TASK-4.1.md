# Task 4.1 — Memory Repository & SQLite FTS5

- Thêm immutable Memory models và Memory types.
- Thêm `MemoryRepository.create`, `get`, `update`, `delete`, `list`.
- Thêm `MemoryRepository.search_fts`.
- Thêm migration `0002_memory_fts5`.
- Tạo FTS5 external-content table.
- Thêm insert/update/delete triggers.
- Rebuild index cho dữ liệu có trước migration.
- Search theo title, content và tags.
- Filter theo scope và memory type.
- Mặc định bỏ qua Memory hết hạn.
- Token hóa query để tránh lỗi FTS syntax.
- Redact secret trước khi lưu.
- Chuẩn hóa SQLite datetime về UTC.
- Thêm integration tests và smoke script.
