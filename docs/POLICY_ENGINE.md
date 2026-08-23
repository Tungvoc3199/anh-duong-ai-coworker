# Deterministic Policy Engine

## API cơ bản

```python
from pathlib import Path

from app.policy import PolicyAction, PolicyEngine

engine = PolicyEngine.with_default_roots()

decision = engine.evaluate(
    PolicyAction(
        name="create_file",
        target_path=Path(
            "/mnt/f/AIOS/project/README.md"
        ),
    )
)

print(decision.kind)
print(decision.rule_id)
```

## Thứ tự đánh giá

1. Chuẩn hóa tên action.
2. Chặn forbidden flags/action.
3. Kiểm tra action trong catalog.
4. Tính risk cao nhất từ catalog, declared risk và effect flags.
5. Kiểm tra workspace/path.
6. Trả `DENY`, `REQUIRE_APPROVAL`, `ALLOW` hoặc `ESCALATE`.

## Quy tắc an toàn

- Policy Engine là pure logic.
- Không gọi LLM.
- Không gọi HTTP.
- Không chạy shell.
- Không truy cập database.
- Cùng input luôn cho cùng output.

## Kiểm tra

```bash
cd /home/thadc/AIOS/anh-duong-core
source .venv/bin/activate

pytest \
  tests/unit/test_policy_engine.py \
  tests/security/test_path_scope.py \
  tests/security/test_policy_determinism.py \
  -q

./scripts/check_policy.sh
./scripts/test.sh
```
