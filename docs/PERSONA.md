# Persona System v1.0

## Nguồn

Persona được nạp theo đúng thứ tự:

1. `data/persona/IDENTITY.md`
2. `data/persona/SOUL.md`
3. `data/persona/USER.md`
4. `data/persona/WORK_STYLE.md`

## Quy tắc version

- Mỗi file phải có YAML frontmatter `version`.
- Tất cả file phải cùng version.
- Thay đổi nội dung Persona phải tăng version và ghi CHANGELOG.
- Loader chuẩn hóa LF trước khi tính SHA-256.

## Kiểm tra

```bash
cd /home/thadc/AIOS/anh-duong-core
./scripts/check_persona.sh
pytest tests/unit/test_persona_loader.py tests/unit/test_persona_content.py -q
```
