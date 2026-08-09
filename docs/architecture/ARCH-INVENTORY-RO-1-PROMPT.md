# ARCH-INVENTORY-RO-1 — Read-only Architecture Inventory

## Mục tiêu
Lập bản kiểm kê kiến trúc **AS-IS** của dự án Ánh Dương AI Coworker dựa trên bằng chứng thực tế từ source, runtime, config, database metadata, tests và checkpoint artifacts; tuyệt đối không thay đổi code/runtime/config/DB/service đang hoạt động.

## Trạng thái phải bảo vệ
- CE-2: đang mở / chưa được coi là CLOSED.
- CACHE-2T: đang mở / chưa được coi là CLOSED.
- Không được trộn scope Architecture Inventory vào CE-2 hoặc CACHE-2T.
- Không được refactor, fix bug, tối ưu, migrate, restart, deploy, commit, checkout/reset, install/update package hoặc thay đổi provider/model/router.
- Production phải giữ nguyên trạng thái vận hành hiện tại.

## Vùng được phép đọc
Ưu tiên workspace Linux đang dùng cho Core:
- `/home/thadc/AIOS/anh-duong-core`

Có thể đọc để đối chiếu nếu tồn tại và không làm thay đổi trạng thái:
- `/mnt/f/AIOS/anh-duong-checkpoints`
- systemd unit/status liên quan Ánh Dương Core
- process/listening-port metadata
- git status/log/diff ở chế độ read-only
- SQLite schema/metadata bằng read-only query
- config files, env *names* và cấu trúc; KHÔNG in secret values
- tests, migrations, docs, AGENTS/PROJECT/STATE/ROADMAP/CHANGELOG nếu có
- OpenClaw/9Router/Telegram integration config ở chế độ chỉ đọc khi cần xác định dependency boundary

## Quy tắc an toàn tuyệt đối
1. Chỉ được thay đổi filesystem ở **thư mục artifact của checkpoint này** để ghi báo cáo/log.
2. Không sửa bất kỳ file source/config/runtime nào.
3. Không chạy command có side effect, bao gồm nhưng không giới hạn: `sed -i`, redirect vào source, `cp/mv/rm`, `git checkout/reset/clean/add/commit`, `systemctl restart/start/stop/reload`, `docker restart/up/down`, `alembic upgrade/downgrade`, `pip/npm/apt install`, DB INSERT/UPDATE/DELETE/DDL, cache flush, kill process.
4. Không expose token/API key/password/cookie/private key. Khi gặp secret chỉ ghi: `PRESENT`, `MISSING`, `SOURCE=<file/env>`.
5. Không chạy test nếu test có thể mutate runtime/DB/queue/external service. Chỉ kiểm kê test suite và đọc cấu hình. Nếu có test chắc chắn isolated/read-only thì có thể liệt kê, không cần chạy.
6. Không kết luận từ memory hoặc assumption. Mỗi mục phải đánh dấu `FACT`, `INFERENCE`, hoặc `UNKNOWN`.
7. Nếu bằng chứng mâu thuẫn giữa docs và runtime, runtime + source hiện hành là source of truth; ghi rõ drift.

## Cross-check gate bắt buộc trước khi inventory
Trước khi đọc sâu:
- Xác nhận repo path thực tế.
- `git status --short --branch`.
- Ghi HEAD commit hiện tại.
- Kiểm tra dirty tree nhưng KHÔNG sửa.
- Xác định service/process/port đang chạy.
- Đọc artifact mới nhất của CE-2 và CACHE-2T để ghi rõ scope đang mở và vùng cấm chạm.
- Nếu không tìm được artifact đủ tin cậy: đánh dấu `UNKNOWN`, không tự suy diễn.

## Nội dung Architecture Inventory
Kiểm kê tối thiểu các domain sau:

### A. Project & Source
1. Project Overview
2. Tech Stack + versions có thể xác minh
3. Folder Structure
4. System Architecture
5. Module Breakdown
6. Dependency Graph
7. Coding conventions / lint / typecheck / test tooling

### B. Request & Business Runtime
8. Request Flow
9. Direct vs Workflow flow
10. Task / Run lifecycle
11. Worker / notification flow
12. Business rules và state transitions quan trọng

### C. Data & Memory
13. Database engine/path/schema overview
14. Alembic/migration status chỉ đọc
15. Memory repository / FTS / retrieval architecture
16. Cache architecture hiện có và boundary của CACHE-2T
17. Transaction/idempotency/retry semantics có thể xác minh

### D. API, Auth, Security
18. API architecture/endpoints chính
19. Authentication
20. Authorization / approval boundaries
21. Validation/error contracts
22. Secrets/config management
23. Security controls thấy được trong source/config

### E. AI / Agent Architecture
24. Model/provider/router architecture
25. Capability/Fast Router
26. Context Builder + token budget
27. Agent/tool execution boundaries
28. Fallback/retry/timeout strategy
29. Cost/token governance nếu có

### F. Operations
30. Runtime topology
31. Service/process ownership
32. Health/readiness
33. Logging/observability
34. Deployment/release pattern
35. Backup/recovery/rollback
36. Production isolation / dev-staging-prod separation
37. Scalability constraints hiện tại

### G. Governance
38. Active checkpoints/tasks
39. Locked/stable/active-development/deprecated components
40. Known technical debt
41. ADR/decision records hiện có
42. Architecture drift: docs vs source vs runtime
43. Improvement candidates — CHỈ GHI NHẬN, KHÔNG TRIỂN KHAI

## Bắt buộc tạo Change Boundary Matrix
Tạo bảng với các cột:
- Component
- Runtime role
- Source path
- Status: `LOCKED | STABLE | ACTIVE_DEVELOPMENT | EXPERIMENTAL | DEPRECATED | UNKNOWN`
- Active checkpoint owner
- Allowed change now? (`NO` cho checkpoint inventory này)
- Dependencies
- Evidence

Đặc biệt làm rõ boundary của:
- Telegram
- OpenClaw
- Ánh Dương Core
- Fast Router
- Capability Router
- Context Builder
- Memory
- CACHE-2T
- CE-2 / Codex execution path
- Async execution worker
- Notification worker
- SQLite/Alembic
- 9Router/model routing

## Bắt buộc tạo Dependency Map
Xuất Mermaid hoặc ASCII diagram thể hiện ít nhất:
`Telegram -> OpenClaw -> Ánh Dương Core -> Router -> Context/Memory -> Direct hoặc Task/Run -> Worker/Agent/Model -> Notification -> Telegram`

Chỉ thêm node/edge khi có bằng chứng.

## Bắt buộc tạo Runtime Truth
Ghi lại trạng thái hiện hành có thể xác minh tại thời điểm chạy:
- repo path
- branch / HEAD
- dirty tree
- Core service state
- health/ready nếu endpoint có thể GET read-only
- listening ports liên quan
- DB path và migration head/current revision nếu đọc được không mutate
- relevant feature flags dưới dạng `NAME=value` chỉ khi value không phải secret
- OpenClaw/9Router integration presence, không thay đổi cấu hình

## Output duy nhất
Tạo thư mục:
`/mnt/f/AIOS/anh-duong-checkpoints/ARCH-INVENTORY-RO-1/`

Chỉ ghi 3 artifact:
1. `ARCH-INVENTORY-RO-1-runtime.log` — toàn bộ command read-only + output đã redacted secrets.
2. `ARCH-INVENTORY-RO-1-report.md` — báo cáo Architecture Inventory đầy đủ.
3. `ARCH-INVENTORY-RO-1-conclusion.md` — kết luận ngắn gồm:
   - PASS/BLOCKED cho inventory
   - FACT/INFERENCE/UNKNOWN
   - architecture coverage hiện có
   - missing/weak domains
   - drift/risk
   - danh sách improvement candidates ưu tiên P0/P1/P2/P3
   - xác nhận CE-2 và CACHE-2T không bị thay đổi

## Điều kiện PASS
Chỉ ghi `ARCH-INVENTORY-RO-1 = PASS` khi:
- Không có source/config/runtime/DB/service nào bị thay đổi.
- Có bằng chứng repo/runtime/checkpoint đủ để lập AS-IS map.
- Có Change Boundary Matrix.
- Có Dependency Map.
- Có Runtime Truth.
- Có Gap Matrix đối chiếu tối thiểu 43 domain ở trên.
- CE-2 và CACHE-2T được ghi đúng trạng thái dựa trên artifact mới nhất, không suy diễn.
- Secrets đã được redacted.

Nếu thiếu bằng chứng quan trọng, ghi `BLOCKED_EVIDENCE_GAP`, nêu chính xác thiếu gì; không sửa gì để “làm cho pass”.

## Cách làm
Tự thực hiện end-to-end trong một lần: inspect -> cross-check -> inventory -> synthesize -> self-review -> artifact.
Không yêu cầu người dùng tự dò file, tự kiểm tra từng đoạn hoặc gửi ảnh trung gian. Chỉ dừng nếu thật sự cần input/approval không thể suy ra bằng read-only inspection.
