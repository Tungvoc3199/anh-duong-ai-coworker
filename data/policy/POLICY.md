---
version: "1.0"
---

# Ánh Dương Core Policy v1.0

## Quyết định

- `ALLOW`: được thực hiện.
- `REQUIRE_APPROVAL`: dừng workflow và xin phê duyệt một lần.
- `DENY`: cấm thực hiện.
- `ESCALATE`: chưa đủ dữ liệu hoặc action chưa đăng ký.

## Risk Level

| Level | Nhóm | Quyết định mặc định |
|---:|---|---|
| 0 | Read-only | Allow |
| 1 | Safe write | Allow trong workspace |
| 2 | Sensitive | Require approval |
| 3 | High risk | Require explicit approval |
| 4 | Forbidden | Deny |

## Giới hạn đường dẫn

Workspace mặc định:

- `/mnt/f/AIOS`
- `/mnt/f/SecondBrain_AI`

Policy chỉ nhận đường dẫn WSL. Không nhận `F:\...`.

## Nguyên tắc bất biến

- LLM không quyết định quyền.
- Không tự approve.
- Không downgrade risk đã khai báo.
- Action lạ phải `ESCALATE`.
- Bypass bảo mật, tắt audit, tự nâng quyền hoặc làm lộ secret phải `DENY`.
