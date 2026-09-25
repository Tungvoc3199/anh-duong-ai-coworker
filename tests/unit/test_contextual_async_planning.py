from app.async_tasks.models import AsyncTaskCreate
from app.async_tasks.service import AsyncTaskService


def test_planning_text_carries_contextual_prior_evidence() -> None:
    request = AsyncTaskCreate(
        project_id="proj_ctx",
        title="Contextual follow-up",
        goal="Sửa lỗi đó giúp a, giữ nguyên phần còn lại.",
        source_channel="telegram",
        source_chat_id="chat-1",
        idempotency_key="telegram:ctx",
        prior_evidence=("quoted_message:5963: lỗi nằm ở contextual referent boundary",),
    )

    text = AsyncTaskService._planning_text(request)

    assert text.startswith("Sửa lỗi đó giúp a, giữ nguyên phần còn lại.")
    assert "[CONTEXTUAL_REFERENCE_DATA]" in text
    assert "quoted_message:5963" in text
