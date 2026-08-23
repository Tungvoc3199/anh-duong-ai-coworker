# Project Markdown Mirror

## Mục tiêu

SQLite là nguồn dữ liệu chính. Markdown là bản mirror để con người đọc,
backup và kết nối với các công cụ như Obsidian.

Mirror root vận hành:

```text
/home/thadc/AIOS/anh-duong-data/projects
```

Mỗi project dùng một thư mục theo slug:

```text
projects/
└── anh-duong-core/
    ├── PROJECT.md
    ├── STATE.md
    ├── CHANGELOG.md
    └── DECISIONS.md
```

## Quy tắc ghi file

### File hệ thống tự cập nhật

- `PROJECT.md`
- `STATE.md`

Hai file này được ghi theo quy trình:

```text
ghi file .tmp cùng thư mục
→ flush
→ fsync file
→ os.replace
→ fsync thư mục
```

Nhờ đó người đọc không nhìn thấy file đang ghi dở.

### File do con người duy trì

- `CHANGELOG.md`
- `DECISIONS.md`

Mirror chỉ tạo hai file này khi chưa tồn tại và không ghi đè nội dung thủ công.

## Bảo mật đường dẫn

Slug phải có dạng:

```text
lowercase-letters-digits-hyphens
```

Slug có `..`, `/`, `\` hoặc ký tự bất hợp lệ bị từ chối để không thoát ra
ngoài mirror root.

## API

```python
from pathlib import Path

from app.projects import ProjectMirror

mirror = ProjectMirror(
    Path("/home/thadc/AIOS/anh-duong-data/projects")
)
project_dir = mirror.write_snapshot(project)
```

## Kiểm tra

```bash
cd /home/thadc/AIOS/anh-duong-core
source .venv/bin/activate

./scripts/check_project_mirror.sh
pytest tests/integration/test_project_mirror.py -q
./scripts/test.sh
```
