"""TOKEN-2 deterministic baseline benchmark (Core-level, no model calls).

Run BEFORE any implementation change to capture the current Context Builder
behavior on the 6 representative workloads A-F.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.capabilities import CapabilityDecision, CapabilityKind  # noqa: E402
from app.context_builder import (  # noqa: E402
    ContextBuilder,
    ContextBuildRequest,
    ContextSectionKind,
    ContextTokenBudget,
    ProjectContextSnapshot,
    TaskContextSnapshot,
)
from app.context_builder.tokens import Utf8ByteTokenEstimator  # noqa: E402
from app.memory import HybridMemorySearchResult, Memory, MemoryType  # noqa: E402
from app.persona import PersonaSnapshot  # noqa: E402
from app.routing import FastRoute, RouteDecision  # noqa: E402

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

PERSONA_FILES = {
    "IDENTITY.md": "# Identity\n\nTôi là Ánh Dương — AI coworker an toàn, "
    "trung thực, tôn trọng ranh giới và quyền riêng tư của người dùng.",
    "SOUL.md": "# Soul\n\nLuôn hành động vì lợi ích của người dùng; không "
    "thực hiện hành động nguy hiểm khi chưa được phê duyệt.",
    "USER.md": "# User\n\nNgười dùng là thadc — kỹ sư phần mềm, làm việc với "
    "AIOS tại /home/thadc/AIOS, giao tiếp tiếng Việt.",
    "WORK_STYLE.md": "# Work Style\n\nƯu tiên thay đổi nhỏ, test trước, bằng "
    "chứng rõ ràng, không phá vỡ công việc đang chạy.",
}
PERSONA = PersonaSnapshot(
    version="1.0",
    language="vi",
    relationship="em-anh",
    tone="direct",
    content_hash="a" * 64,
    file_order=tuple(PERSONA_FILES),
    files=PERSONA_FILES,
    combined_content="\n\n".join(PERSONA_FILES.values()),
)


def memory(
    memory_id: str,
    content: str,
    *,
    score: float = 0.5,
    mtype: MemoryType = MemoryType.PROJECT,
    scope_id: str = "proj_1",
    importance: float = 0.5,
    recency: float = 0.5,
    updated_days_ago: float = 30.0,
    title: str | None = None,
) -> HybridMemorySearchResult:
    updated = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    return HybridMemorySearchResult(
        memory=Memory(
            id=memory_id,
            memory_type=mtype,
            scope_id=scope_id,
            title=title or f"Memory {memory_id}",
            content=content,
            summary=None,
            importance=importance,
            confidence=0.8,
            source="benchmark",
            expires_at=None,
            tags=(),
            created_at=updated,
            updated_at=updated,
            version=1,
        ),
        fts_rank=-float(memory_id.count("x")) - 1.0,
        lexical_score=score,
        importance_score=importance,
        confidence_score=0.8,
        recency_score=recency,
        hybrid_score=score,
    )


class RecordingRetriever:
    def __init__(self, results: list[HybridMemorySearchResult]) -> None:
        self.results = results
        self.calls = 0

    def retrieve(self, query: str, **kwargs):
        self.calls += 1
        return list(self.results)


def route(route: FastRoute, rule: str, reason: str) -> RouteDecision:
    return RouteDecision(route=route, rule_id=rule, reason=reason)


def capability(cap: CapabilityKind, route_: FastRoute, code: str) -> CapabilityDecision:
    return CapabilityDecision(
        capability=cap,
        source_route=route_,
        reason_code=code,
        matched_signals=(code,),
    )


def project_snapshot(*, with_history: bool = True) -> ProjectContextSnapshot:
    history = (
        "FR-1 đã PASS: context builder deterministic.",
        "FR-2 đã PASS: caching L1 hoạt động.",
        "CE-2 đang điều tra: profile test runner.",
        "CACHE-2T-L1 đã đóng: flags true/true/false.",
    ) if with_history else ()
    return ProjectContextSnapshot(
        identity="anh-duong-core",
        goal="Build Ánh Dương AI Coworker",
        current_phase="TOKEN-2",
        architecture_constraints=("Không đổi DB schema", "Không thêm dependency"),
        decisions=("Dùng dependency injection", "Deterministic selection"),
        status="TOKEN-1 và CACHE-2T-L1 đã đóng",
        history=history,
    )


def task_snapshot() -> TaskContextSnapshot:
    return TaskContextSnapshot(
        identity="CB-1",
        active_goal="Build Context Builder v1",
        status="implementing",
        constraints=("Không gọi LLM", "Không đổi cache internals"),
        acceptance_criteria=("Giảm ≥30% tokens", "Regression bằng 0"),
        blockers=(),
        next_action="Chạy benchmark trước/sau",
        history=(
            "Đã map pipeline hiện tại.",
            "Đã viết spec thiết kế.",
            "Đang cài đặt selection stage.",
        ),
    )


def budget() -> ContextTokenBudget:
    return ContextTokenBudget()


BIG_MEMORY_BODY = "Nội dung dài. " + ("chi tiết lịch sử quyết định kỹ thuật. " * 40)


def build_request(
    *,
    request_text: str,
    route_: FastRoute,
    cap: CapabilityKind,
    project: ProjectContextSnapshot | None = None,
    task: TaskContextSnapshot | None = None,
    memory_scope: str | None = "proj_1",
) -> ContextBuildRequest:
    return ContextBuildRequest(
        current_request=request_text,
        persona=PERSONA,
        fast_router_decision=route(route_, f"rule.{route_.value}", "benchmark rule"),
        capability_decision=capability(cap, route_, f"cap.{cap.value}"),
        project_context=project,
        task_context=task,
        token_budget=budget(),
        memory_scope_id=memory_scope,
    )


def workloads():
    w = {}
    # A. DIRECT-SHORT
    w["A-DIRECT-SHORT"] = (
        build_request(
            request_text="Chào Ánh Dương, hôm nay thế nào?",
            route_=FastRoute.DIRECT,
            cap=CapabilityKind.CONVERSATIONAL_RESPONSE,
            project=None,
            task=None,
            memory_scope=None,
        ),
        RecordingRetriever([]),
        {"route": "direct", "capability": "conversational_response",
         "facts": ("Chào Ánh Dương",)},
    )
    # B. DIRECT-WITH-MEMORY
    relevant = [
        memory("mem_b1", "Người dùng thích làm việc vào buổi sáng và ưu tiên "
               "các thay đổi nhỏ.", score=0.9, mtype=MemoryType.USER,
               scope_id="user_thadc", importance=0.9, recency=0.9),
        memory("mem_b2", "Dự án hiện tại: AIOS — checkpoint TOKEN-2.", score=0.8,
               mtype=MemoryType.PROJECT, scope_id="proj_1", importance=0.8,
               recency=0.8),
    ]
    w["B-DIRECT-WITH-MEMORY"] = (
        build_request(
            request_text="Sáng nay mình nên làm gì tiếp theo cho AIOS?",
            route_=FastRoute.DIRECT,
            cap=CapabilityKind.CONVERSATIONAL_RESPONSE,
            project=project_snapshot(with_history=False),
            task=None,
            memory_scope="user_thadc",
        ),
        RecordingRetriever(relevant),
        {"route": "direct", "capability": "conversational_response",
         "facts": ("mem_b1", "mem_b2", "AIOS")},
    )
    # C. WORKFLOW
    w["C-WORKFLOW"] = (
        build_request(
            request_text="Triển khai selection stage cho Context Builder và "
            "chạy benchmark.",
            route_=FastRoute.WORKFLOW,
            cap=CapabilityKind.CODE_OPERATION,
            project=project_snapshot(),
            task=task_snapshot(),
        ),
        RecordingRetriever([memory("mem_c1", BIG_MEMORY_BODY, score=0.7)]),
        {"route": "workflow", "capability": "code_operation",
         "facts": ("anh-duong-core", "CB-1", "Build Context Builder v1",
                   "Triển khai selection stage")},
    )
    # D. MEMORY-NOISE
    noise = [memory(f"mem_dn{i:02d}", "Ghi chú cũ không liên quan. " + "n" * 300,
                    score=0.05 + i * 0.01) for i in range(18)]
    relevant_d = [
        memory("mem_d1", "Quyết định: selection phải deterministic, không gọi "
               "LLM.", score=0.95, importance=0.95, recency=0.95),
        memory("mem_d2", "Constraint: không sửa cache internals trong TOKEN-2.",
               score=0.9, importance=0.9, recency=0.9),
    ]
    w["D-MEMORY-NOISE"] = (
        build_request(
            request_text="Tóm tắt các quyết định và constraint của TOKEN-2.",
            route_=FastRoute.MEMORY,
            cap=CapabilityKind.MEMORY_SEARCH,
            project=project_snapshot(with_history=False),
            task=None,
        ),
        RecordingRetriever(relevant_d + noise),
        {"route": "memory", "capability": "memory_search",
         "facts": ("mem_d1", "mem_d2")},
    )
    # E. DUPLICATE-CONTEXT
    dup_project = ProjectContextSnapshot(
        identity="anh-duong-core",
        goal="Build Ánh Dương AI Coworker",
        current_phase="TOKEN-2",
        architecture_constraints=("Không đổi DB schema",),
        decisions=("Dùng dependency injection",),
        status="TOKEN-1 đã đóng",
        history=("CACHE-2T-L1 đã đóng với flags true/true/false.",),
    )
    dup_memory = memory(
        "mem_e1",
        "CACHE-2T-L1 đã đóng với flags true/true/false.",
        score=0.85,
        importance=0.85,
        recency=0.85,
    )
    w["E-DUPLICATE-CONTEXT"] = (
        build_request(
            request_text="Trạng thái CACHE-2T-L1 hiện tại?",
            route_=FastRoute.CORE_READ,
            cap=CapabilityKind.PROJECT_READ,
            project=dup_project,
            task=None,
        ),
        RecordingRetriever([dup_memory]),
        {"route": "core_read", "capability": "project_read",
         "facts": ("CACHE-2T-L1 đã đóng",)},
    )
    # F. LARGE-CONTEXT
    many = [
        memory(f"mem_f{i:02d}", BIG_MEMORY_BODY + f" tag {i}", score=0.5 + (i % 5) * 0.1)
        for i in range(20)
    ]
    w["F-LARGE-CONTEXT"] = (
        build_request(
            request_text="Phân tích toàn bộ ngữ cảnh dự án và đề xuất kế "
            "hoạch tiếp theo cho checkpoint.",
            route_=FastRoute.WORKFLOW,
            cap=CapabilityKind.PLANNING,
            project=project_snapshot(),
            task=task_snapshot(),
        ),
        RecordingRetriever(many),
        {"route": "workflow", "capability": "planning",
         "facts": ("anh-duong-core", "CB-1")},
    )
    return w


def estimate(bundle) -> dict:
    return {
        "sections": {
            s.kind.value: {"tokens": s.estimated_tokens, "truncated": s.truncated}
            for s in bundle.sections
        },
        "total_estimated_tokens": bundle.estimated_tokens,
        "usable": bundle.token_budget.usable_context_tokens,
        "remaining": bundle.remaining_tokens,
        "dropped": [
            {"section": d.section.value, "reason": d.reason,
             "orig": d.original_estimated_tokens}
            for d in bundle.dropped_items
        ],
        "truncated_count": len(bundle.truncated_items),
        "memories_in": sum(1 for s in bundle.sections
                           if s.kind is ContextSectionKind.RELEVANT_MEMORY
                           and "id: " in s.content),
        "warnings": list(bundle.warnings),
    }


def main() -> None:
    estimator = Utf8ByteTokenEstimator()
    ws = workloads()
    out = {"generator": "token2-baseline", "estimator": "Utf8ByteTokenEstimator",
           "workloads": {}}
    for name, (request, retriever, golden) in sorted(ws.items()):
        started = time.perf_counter()
        builder = ContextBuilder(retriever, estimator)
        bundle = builder.build(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        est = estimate(bundle)
        est["latency_ms"] = round(elapsed_ms, 3)
        est["retrieval_calls"] = retriever.calls
        est["golden"] = golden
        est["facts_present"] = all(f in bundle.rendered_context for f in golden["facts"])
        out["workloads"][name] = est
        print(f"{name}: {est['total_estimated_tokens']} tokens "
              f"({elapsed_ms:.1f}ms) facts={est['facts_present']} "
              f"calls={retriever.calls}")
    payload = json.dumps(out, indent=1, ensure_ascii=False)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(payload, encoding="utf-8")
        print(f"json written to {sys.argv[1]}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
