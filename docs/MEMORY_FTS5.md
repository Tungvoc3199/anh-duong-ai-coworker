# Memory Repository & SQLite FTS5

## Mục tiêu

Task 4.1 cung cấp lớp lưu trữ Memory dài/ngắn hạn và tìm kiếm full-text
không cần vector database.

SQLite là nguồn dữ liệu chính. FTS5 là chỉ mục tìm kiếm.

## Memory types

```text
working
session
project
user
episodic
semantic
```

## Interface

```python
MemoryRepository.create(...)
MemoryRepository.get(memory_id)
MemoryRepository.update(memory_id, changes)
MemoryRepository.delete(memory_id)
MemoryRepository.list(...)
MemoryRepository.search_fts(...)
```

## Kiến trúc FTS5

Migration `0002` tạo external-content table:

```sql
CREATE VIRTUAL TABLE memories_fts USING fts5(
  title,
  content,
  tags,
  content='memories',
  content_rowid='rowid'
);
```

Ba trigger giữ chỉ mục đồng bộ:

```text
memories_fts_ai  — after insert
memories_fts_ad  — after delete
memories_fts_au  — after update
```

Dùng migration mới thay vì sửa migration `0001` vì database thật của anh đã được
khởi tạo. `alembic upgrade head` sẽ nâng cấp an toàn từ `0001` lên `0002`.

## Search behavior

- Search trên `title`, `content`, `tags`.
- Có thể filter theo `scope_id`.
- Có thể filter theo `memory_type`.
- Mặc định không trả Memory đã hết hạn.
- Query người dùng được token hóa và quote trước `MATCH`, tránh lỗi cú pháp FTS.
- Sort theo `bm25`, sau đó importance và thời gian cập nhật.

Hybrid ranking đầy đủ nằm ở Task 4.2.

## Memory safety

Trước khi lưu hoặc cập nhật:

- Redact API key.
- Redact password/token/secret.
- Redact sensitive tags.
- Giữ importance/confidence trong khoảng `0..1`.

## Ví dụ

```python
from sqlalchemy.orm import Session

from app.memory import (
    MemoryRepository,
    MemoryType,
)

repository = MemoryRepository(session)

repository.create(
    memory_type=MemoryType.PROJECT,
    scope_id="proj_anh_duong_core",
    title="Runtime architecture",
    content="Core chạy bằng systemd trên WSL.",
    importance=0.9,
    confidence=1.0,
    tags=("systemd", "wsl"),
)

results = repository.search_fts(
    "systemd WSL",
    scope_id="proj_anh_duong_core",
)
```

## Kiểm tra trên máy anh

```bash
cd /home/thadc/AIOS/anh-duong-core
source .venv/bin/activate

alembic upgrade head
./scripts/check_memory_fts.sh
pytest tests/integration/test_memory_fts.py -q
./scripts/test.sh
```
