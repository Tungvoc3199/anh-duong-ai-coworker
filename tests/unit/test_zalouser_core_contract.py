from app.orchestration.models import CoreRequest
from app.privacy import telegram_idempotency_key
from tests.unit.test_core_request_pipeline_behavior import ProjectReader, _pipeline, _project

def test_zalouser_prepare_preserves_channel_identity_and_exactly_once_key():
    project = _project()
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text="Soạn checklist 5 bước kiểm tra trạng thái Ánh Dương Core theo chế độ chỉ đọc. Không chạy lệnh, không sửa file, không restart dịch vụ.",
            request_id="zalo-run-1", channel="zalouser", actor="zalouser:actor-hash",
            source_origin="zalouser_user", source_chat_id="chat-42",
            source_session_id="session-42", source_message_id="message-99",
        )
    )
    assert prepared.workflow is not None
    assert prepared.workflow.source_channel == "zalouser"
    assert prepared.workflow.requested_by == "zalouser:actor-hash"
    assert prepared.workflow.idempotency_key is not None
    assert prepared.workflow.idempotency_key.startswith("zalouser:")
    assert prepared.workflow.idempotency_key != telegram_idempotency_key(source_chat_id="chat-42", source_message_id="message-99")
