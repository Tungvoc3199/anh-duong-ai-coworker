# CB-1 Context Builder v1 — Thiết kế

## Kết quả cần đạt

Thêm một application service thuần và deterministic để kết hợp Persona, quyết định
FR-1/CR-1, snapshot Project/Task, Hybrid Memory Retrieval và yêu cầu hiện tại thành
một `ContextBundle` có ngân sách token ước lượng, provenance, cảnh báo và metadata
drop/truncate. Service không gọi LLM, không thực thi capability, không gọi OpenClaw
và không được nối vào Telegram.

## Các phương án đã cân nhắc

1. **Typed snapshots + dependency injection (chọn):** tạo contract Pydantic frozen
   cho input/output và inject retriever/estimator. Phương án này phù hợp convention
   hiện tại, unit test không cần database và không tạo persistence mới.
2. **Nhận `dict[str, Any]` tự do:** ít model hơn nhưng khó bảo đảm field ordering,
   mandatory fields, provenance và mypy strict.
3. **Builder tự đọc database:** tiện cho consumer nhưng trộn composition, retrieval
   và rendering; làm unit test cần database và vượt phạm vi CB-1.

Đặc tả one-shot đã chỉ định ưu tiên service thuần, deterministic, dependency
injection và yêu cầu tự chọn quyết định kỹ thuật thông thường, nên phương án 1 là
thiết kế đã được chấp thuận cho lần triển khai này.

## Package và public contract

Tạo package `app.context_builder`:

- `models.py`: `ContextTokenBudget`, `ProjectContextSnapshot`,
  `TaskContextSnapshot`, `ContextBuildRequest`, `ContextSection`,
  `ContextItemChange`, `ContextProvenance`, `ContextBundle` và
  `ContextBudgetExceededError`.
- `tokens.py`: protocol `TokenEstimator` và implementation bảo thủ
  `Utf8ByteTokenEstimator`, dùng `max(1, ceil(UTF-8 bytes / 4))` cho text không rỗng.
- `builder.py`: `ContextBuilder`, pure ngoài đúng một lần gọi retriever.
- `wiring.py`: factory nhận SQLAlchemy `Session`, ghép `MemoryRepository` →
  `HybridMemoryRetriever` → `ContextBuilder`.
- `__init__.py`: public exports ổn định.

`ContextBuildRequest` tái sử dụng trực tiếp `PersonaSnapshot`, `RouteDecision` và
`CapabilityDecision`. Project/Task dùng input snapshot typed vì model persistence
hiện tại không chứa active goal, acceptance criteria hoặc history đầy đủ.

## Token budget

`ContextTokenBudget` là frozen model với mặc định:

- context window: 16.000;
- response reserve: 3.000;
- runtime reserve: 1.000;
- usable context: computed 12.000;
- soft allocations: Persona 1.200, Routing 800, Task 3.200, Project 2.400,
  Memory 4.400.

Mọi giá trị được validate và soft allocation không phải hard partition. Builder
đánh giá toàn bộ rendered context trên shared usable pool, vì vậy token chưa dùng
của section này tự động có thể được section khác dùng. Không có dependency tokenizer
mới và metadata luôn ghi đây là estimated tokens.

## Data flow và ordering

1. Validate input bất biến và redact secret bằng `SecretRedactor` hiện có.
2. Tạo retrieval query ổn định từ current request, task goal, project identity/goal,
   Fast Route và Capability Kind.
3. Gọi injected Hybrid Memory Retriever đúng một lần.
4. Stable-sort tie theo memory ID, deduplicate theo memory ID và giữ provenance.
5. Tạo sáu draft section theo thứ tự Persona, Routing Decisions, Project Context,
   Active Task, Relevant Memory, Current Request.
6. Áp dụng reduction policy nếu tổng ước lượng vượt usable budget.
7. Render marker rõ ràng và trả frozen `ContextBundle`.

Marker cuối là `[PERSONA]`, `[ROUTING_DECISIONS]`, `[PROJECT_CONTEXT]`,
`[ACTIVE_TASK]`, `[RELEVANT_MEMORY]`, `[CURRENT_REQUEST]` theo đúng thứ tự trên.

## Reduction và error policy

Trước hết duplicate memory bị loại và ghi `dropped_items`. Khi vượt ngân sách,
builder lần lượt loại memory relevance thấp nhất, truncate body memory dài nhưng giữ
ID/source/title, loại project history cũ, loại task history cũ và cuối cùng loại
persona example files. Mọi thay đổi đều tạo `ContextItemChange`.

Current request, router decisions, task active goal/constraints/status/acceptance
criteria/next action, project architecture constraints và persona identity/core files
không bị loại. Nếu phần bắt buộc vẫn vượt usable budget, builder raise
`ContextBudgetExceededError` với required estimate và usable budget; không trả bundle
thiếu nội dung bắt buộc và không âm thầm vượt budget.

## Retrieval failure và determinism

`MemoryRepositoryError` và SQLAlchemy errors được xem là recoverable: builder tạo
bundle không có memory thật và thêm warning, không giả dữ liệu. Empty retrieval là
thành công bình thường. Validation/programming errors không bị nuốt.

Cùng input, cùng memory result và cùng estimator tạo cùng section order, rendered
text, metadata và provenance. Builder không dùng clock, randomness, set iteration
hoặc unordered object `repr()`.

## Wiring và safety boundary

`create_context_builder(session)` là composition factory duy nhất. `create_app()`
đăng ký factory trên `app.state` nhưng không gọi nó, không mở session, không chạy
retrieval và không đổi request path đang hoạt động. Không sửa schema, migration,
systemd, Async Worker, OpenClaw, Telegram hoặc 9Router.

## Verification

TDD theo ba vòng: contract/token estimator, builder behavior, wiring. Sau targeted
tests sẽ chạy full Pytest, Ruff, Mypy app, Compileall; sau đó kiểm tra Core active,
health/ready HTTP 200, Alembic 0003, Async Worker false và systemd override còn nguyên.
Toàn bộ bằng chứng cuối được ghi vào đúng một file checkpoint CB-1.

