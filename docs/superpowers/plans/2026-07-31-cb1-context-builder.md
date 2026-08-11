# CB-1 Context Builder v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây Context Builder v1 deterministic, typed và giới hạn trong 12.000 estimated tokens mặc định.

**Architecture:** Frozen Pydantic contracts bao quanh một service thuần. Service
consume upstream router decisions, gọi injected Hybrid Memory Retriever đúng một
lần, render sáu section ổn định và giảm optional content theo policy trước khi trả
bundle có provenance đầy đủ.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2, Pytest, Ruff, Mypy, WSL/PowerShell.

## Global Constraints

- Không gọi LLM, capability/skill, OpenClaw, Telegram hoặc 9Router.
- Không thêm dependency, schema, Alembic migration, database query trực tiếp hoặc persistence mới.
- Không bật Async Worker, không sửa systemd unit/override và giữ runtime Alembic `0003`.
- Default budget là `16000 - 3000 - 1000 = 12000` estimated tokens.
- Current request, router decisions, safety constraints và persona core không được âm thầm loại.
- Không commit/push/deploy; workspace hiện không có Git metadata.

---

### Task 1: Public contracts và token estimator

**Files:**
- Create: `app/context_builder/models.py`
- Create: `app/context_builder/tokens.py`
- Create: `app/context_builder/__init__.py`
- Test: `tests/unit/test_context_builder_models.py`

**Interfaces:**
- Consumes: `PersonaSnapshot`, `RouteDecision`, `CapabilityDecision`.
- Produces: `ContextTokenBudget.usable_context_tokens`, typed input/output models,
  `TokenEstimator.estimate(text: str) -> int`, `Utf8ByteTokenEstimator`.

- [ ] Viết failing tests xác nhận default/custom/invalid budget, current request bắt
  buộc, frozen models, Vietnamese UTF-8 estimator và public exports.
- [ ] Chạy
  `.venv/bin/python -m pytest -q tests/unit/test_context_builder_models.py`
  và xác nhận RED do package chưa tồn tại.
- [ ] Tạo frozen models; dùng `model_validator(mode="after")` để reject usable budget
  không dương và `field_validator` để strip/reject request rỗng.
- [ ] Tạo estimator:

```python
class Utf8ByteTokenEstimator:
    def estimate(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text.encode("utf-8")) / 4))
```

- [ ] Export contract và chạy lại targeted test để xác nhận GREEN.

### Task 2: Builder ordering, retrieval và budget reduction

**Files:**
- Create: `app/context_builder/builder.py`
- Test: `tests/unit/test_context_builder.py`

**Interfaces:**
- Consumes: `ContextBuildRequest`, injected retriever có method tương thích
  `HybridMemoryRetriever.retrieve`, injected `TokenEstimator`, `SecretRedactor`.
- Produces: `ContextBuilder.build(request: ContextBuildRequest) -> ContextBundle`.

- [ ] Viết failing test đầu tiên cho full bundle: sáu marker đúng thứ tự, consume
  upstream decisions, retrieval query chứa request/task/project/route/capability,
  retriever gọi đúng một lần và memory provenance được giữ.
- [ ] Chạy test cụ thể và xác nhận RED do `ContextBuilder` chưa tồn tại.
- [ ] Implement query builder, one-shot retrieval, six draft sections, exact marker
  order, stable field formatting và total/remaining estimated token metadata.
- [ ] Chạy lại test đầu tiên để xác nhận GREEN.
- [ ] Thêm từng failing test rồi minimal implementation cho: deterministic repeated
  builds; empty project/task/memory; recoverable retrieval warning; duplicate memory;
  stable equal-score order; Vietnamese Unicode; không mutate input.
- [ ] Thêm từng failing test rồi minimal implementation cho budget: custom budget,
  total không vượt usable, shared-pool reallocation, low-relevance memory drop,
  long-memory truncation, project/task old-history drop, persona-example drop và
  precise changed-item metadata.
- [ ] Thêm failing test required-only overflow rồi implement
  `ContextBudgetExceededError(required_tokens, usable_tokens)`; xác nhận current
  request/router/persona core/task constraints không bị loại.
- [ ] Chạy toàn bộ `tests/unit/test_context_builder.py` sau mỗi refactor và giữ GREEN.

### Task 3: Composition wiring không kích hoạt runtime flow

**Files:**
- Create: `app/context_builder/wiring.py`
- Modify: `app/main.py`
- Test: `tests/integration/test_context_builder_wiring.py`

**Interfaces:**
- `create_context_builder(session: Session) -> ContextBuilder` ghép
  `MemoryRepository(session)` với `HybridMemoryRetriever`.
- `create_app()` expose callable qua `application.state.context_builder_factory`
  nhưng không gọi factory hoặc retriever.

- [ ] Viết failing integration test xác nhận factory được export/đăng ký và app
  creation không gọi retrieval, OpenClaw hoặc capability execution.
- [ ] Chạy test cụ thể và xác nhận RED do wiring chưa tồn tại.
- [ ] Implement factory, export symbol và gắn factory vào app state mà không đổi
  lifespan/request routes.
- [ ] Chạy integration test để xác nhận GREEN.

### Task 4: Targeted và full verification

**Files:**
- Modify only CB-1 files if a verified regression requires correction.

**Interfaces:**
- Consumes all CB-1 source/tests and existing FR-1/CR-1/Hybrid Memory tests.
- Produces fresh command evidence for the final checkpoint.

- [ ] Chạy targeted suite gồm Context Builder, Fast Router, Capability Router,
  Hybrid Memory Retrieval và wiring tests; yêu cầu zero failures.
- [ ] Chạy `.venv/bin/python -m pytest -q`; số PASS phải lớn hơn baseline 267.
- [ ] Chạy `.venv/bin/python -m ruff check .`, `.venv/bin/python -m mypy app` và
  `.venv/bin/python -m compileall -q app tests alembic`; tất cả exit 0.
- [ ] Nếu có lỗi, thêm failing regression test trước khi sửa production code.

### Task 5: Runtime, safety và checkpoint duy nhất

**Files:**
- Create outside repo: `/mnt/f/AIOS/anh-duong-checkpoints/checkpoint-CB-1.log`

**Interfaces:**
- Consumes verified command outputs.
- Produces one final PASS/FAIL checkpoint without secret values.

- [ ] Kiểm tra `systemctl is-active anh-duong-core.service`, `/health`, `/ready`,
  runtime Alembic current revision, process environment Async Worker flag và nội
  dung/hash systemd safety override bằng read-only commands.
- [ ] Xác nhận không có migration/schema, Telegram/OpenClaw/9Router/systemd changes.
- [ ] Ghi đủ 24 mục bắt buộc vào đúng một checkpoint log bằng một atomic write.
- [ ] Đọc lại checkpoint, đối chiếu Definition of Done và chỉ kết luận `CB-1 PASS`
  khi mọi bằng chứng fresh đều đạt.

## Self-review

Kế hoạch bao phủ toàn bộ input/output contract, budget, shared pool, ordering,
reduction, retrieval one-shot/degradation, provenance, edge cases, wiring, full
verification và safety constraints. Signature và type name nhất quán; không có
placeholder hoặc subsystem ngoài CB-1.

