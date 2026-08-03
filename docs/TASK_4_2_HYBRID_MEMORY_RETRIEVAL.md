# Task 4.2 — Hybrid Memory Retrieval

## 1. Mục tiêu

Xây lớp retrieval deterministic trên `MemoryRepository.search_fts` để kết hợp:
- lexical relevance;
- importance;
- confidence;
- recency.

Không thay schema database và không dùng vector embedding.

## 2. Phạm vi

Tạo dự kiến:
- `app/memory/retrieval.py`
- `tests/unit/test_memory_retrieval.py`

Có thể sửa tối thiểu:
- `app/memory/models.py`
- `app/memory/__init__.py`

Không sửa migration `0002` và không thay đổi behavior hiện tại của `search_fts`.

## 3. Candidate Retrieval

Dùng `MemoryRepository.search_fts` với:

```python
candidate_limit = min(max(limit * 4, 20), 100)
```

Giữ nguyên các filter hiện có:
- `scope_id`;
- `memory_type`;
- `include_expired`.

Query rỗng hoặc không có token hợp lệ phải trả `[]` mà không thực hiện retrieval.

## 4. Ranking Contract

Các tín hiệu:

```python
lexical_score = 1 / (1 + zero_based_fts_position)

importance_score = clamp(memory.importance, 0, 1)

confidence_score = clamp(memory.confidence, 0, 1)

age_days = max((now - memory.updated_at).total_seconds() / 86400, 0)

recency_score = 1 / (1 + age_days / 30)

hybrid_score = (
    0.60 * lexical_score
    + 0.15 * importance_score
    + 0.15 * confidence_score
    + 0.10 * recency_score
)
```

`hybrid_score` phải được clamp trong khoảng `[0, 1]`.

Không chuẩn hóa trực tiếp giá trị BM25 vì FTS5 BM25 có thang đo không phù hợp để trộn thẳng với metadata.

## 5. Stable Sorting

Sắp xếp theo thứ tự:

1. `hybrid_score` DESC
2. `fts_rank` ASC
3. `importance` DESC
4. `updated_at` DESC
5. `memory.id` ASC

Cùng input và cùng `now` phải luôn trả cùng thứ tự.

## 6. Result Contract

Result tối thiểu phải chứa:
- `memory`
- `fts_rank`
- `lexical_score`
- `importance_score`
- `confidence_score`
- `recency_score`
- `hybrid_score`

Không làm mất các trường hiện có của `Memory`.

## 7. Edge Cases

| Điều kiện | Hành vi mong đợi |
|---|---|
| query rỗng | `[]` |
| query không có token hợp lệ | `[]` |
| không có candidate | `[]` |
| limit ngoài giới hạn hiện có | giữ validation thống nhất với repository |
| memory hết hạn | Bị loại mặc định |
| `include_expired=True` | Cho phép lấy memory hết hạn |
| `updated_at` trong tương lai | `age_days = 0` |
| `importance` / `confidence` ngoài `[0, 1]` | Được clamp về `[0, 1]` |

## 8. TDD Plan

### RED đầu tiên

- Tạo hai candidate có thứ tự lexical khác nhau;
- Metadata của candidate thứ hai đủ mạnh để thay đổi thứ tự cuối;
- Test thất bại vì `HybridMemoryRetriever` chưa tồn tại.

### Các test tiếp theo

- Tất cả score nằm trong `[0, 1]`;
- Stable tie-breaking bằng `memory.id`;
- Query rỗng trả `[]`;
- Expired filtering được giữ nguyên;
- Limit được áp dụng sau ranking;
- Cùng `now` cho kết quả deterministic.

## 9. Ngoài phạm vi

- Vector database;
- Embedding provider;
- Semantic model call;
- Context Builder;
- Fast Router;
- Telegram routing;
- Thay đổi OpenClaw hoặc 9Router;
- Migration database mới.