# Task 2.2 — Deterministic Policy Engine

- Thêm Risk Level 0–4.
- Thêm Allow, Require Approval, Deny và Escalate.
- Thêm action catalog deterministic.
- Không cho declared risk hạ thấp catalog risk.
- Effect flags có thể tự nâng risk.
- Thêm workspace allowlist và path normalization.
- Chặn traversal, sibling escape, symlink escape và Windows path.
- Action chưa đăng ký luôn Escalate.
- Forbidden flags luôn Deny, kể cả action chưa đăng ký.
- Thêm unit/security tests và script kiểm tra.
