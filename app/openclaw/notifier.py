from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.async_tasks.models import (
    AsyncRunStatus,
    AsyncTaskRun,
)
from app.audit import SecretRedactor
from app.capabilities import CapabilityKind, CapabilityRouter
from app.openclaw.models import OpenClawTransportError
from app.routing import FastRouter

TERMINAL_RUN_STATUSES = {
    AsyncRunStatus.COMPLETED,
    AsyncRunStatus.FAILED,
    AsyncRunStatus.BLOCKED,
    AsyncRunStatus.CANCELLED,
}
_IMAGE_PROFILE = "visualforge-v0.2+openclaw-image"
_IMAGE_TASK_CONSTRAINTS = frozenset({
    "one_image_max",
    "subscription_quota_only",
    "no_paid_fallback",
    "retry_delivery_without_regeneration",
})


class OpenClawNotifier:
    def __init__(
        self,
        *,
        base_url: str,
        notification_path: str = "/tools/invoke",
        auth_token: str | None = None,
        image_media_root: str = "/home/node/.openclaw/media/anh-duong",
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self.redactor = redactor or SecretRedactor()
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )
        self.notification_path = (
            "/" + notification_path.lstrip("/")
        )
        normalized_image_root = "/" + image_media_root.strip().strip("/")
        if not normalized_image_root.startswith("/home/node/.openclaw/media/"):
            raise ValueError("image_media_root must be within OpenClaw managed media")
        self.image_media_root = normalized_image_root
        self.auth_token = auth_token

    async def send_final(
        self,
        run: AsyncTaskRun,
    ) -> None:
        if run.status not in TERMINAL_RUN_STATUSES:
            raise ValueError(
                "Only terminal runs may be notified"
            )
        if not run.source_chat_id:
            raise ValueError(
                "Telegram notification requires source_chat_id"
            )

        headers = {
            "Content-Type": "application/json",
        }
        if self.auth_token:
            headers["Authorization"] = (
                f"Bearer {self.auth_token}"
            )

        idempotency_key = f"notify:{run.id}:{run.status.value}"
        media = self._image_media(run)
        args = {
            "action": "send",
            "channel": "telegram",
            "target": run.source_chat_id,
            "message": self._message(run, image_media_present=media is not None),
            "idempotencyKey": idempotency_key,
        }
        if media is not None:
            args.update({"media": media[0], "mimeType": media[1]})
        payload = {
            "tool": "message",
            "args": args,
            "idempotencyKey": idempotency_key,
        }

        try:
            response = await self._client.post(
                self.notification_path,
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException as error:
            raise OpenClawTransportError(
                "timeout",
                "OpenClaw notification timed out.",
                retryable=True,
            ) from error
        except httpx.ConnectError as error:
            raise OpenClawTransportError(
                "connection_error",
                "OpenClaw notification connection failed.",
                retryable=True,
            ) from error
        except httpx.HTTPError as error:
            raise OpenClawTransportError(
                "transport_error",
                str(self.redactor.redact(str(error))),
                retryable=True,
            ) from error

        if response.status_code >= 400:
            raise self._http_error(response)

        try:
            body = response.json()
        except ValueError as error:
            raise OpenClawTransportError(
                "invalid_response",
                "OpenClaw notifier returned invalid JSON.",
                retryable=False,
            ) from error

        if not isinstance(body, dict) or body.get("ok") is not True:
            raise OpenClawTransportError(
                "notification_failed",
                str(self.redactor.redact(body))[:2000],
                retryable=False,
            )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _image_media(self, run: AsyncTaskRun) -> tuple[str, str] | None:
        if not run.result_json:
            return None
        try:
            result = json.loads(run.result_json)
        except json.JSONDecodeError as error:
            raise OpenClawTransportError(
                "notification_artifact_invalid",
                "Image result JSON is invalid.",
                retryable=False,
            ) from error
        profile = result.get("profile") if isinstance(result, dict) else None
        artifacts = result.get("artifacts") if isinstance(result, dict) else None
        image = artifacts.get("image") if isinstance(artifacts, dict) else None
        if image is None:
            if profile == _IMAGE_PROFILE:
                raise OpenClawTransportError(
                    "notification_artifact_invalid",
                    "Image profile requires exactly one verified managed image.",
                    retryable=False,
                )
            return None
        verification = result.get("verification") if isinstance(result, dict) else None
        if not isinstance(image, dict) or not isinstance(verification, dict):
            raise OpenClawTransportError(
                "notification_artifact_invalid",
                "Image artifact verification is missing.",
                retryable=False,
            )
        if verification.get("image_artifact_verified") is not True:
            raise OpenClawTransportError(
                "notification_artifact_invalid",
                "Image artifact was not verified.",
                retryable=False,
            )
        media_path = image.get("media_path")
        prefix = f"{self.image_media_root}/"
        if (
            not isinstance(media_path, str)
            or any(ord(char) < 32 or ord(char) == 127 for char in media_path)
            or not media_path.startswith(prefix)
            or ".." in media_path
            or media_path != prefix + Path(media_path).name
            or image.get("mime_type") != "image/png"
        ):
            raise OpenClawTransportError(
                "notification_artifact_invalid",
                "Image media path or MIME is invalid.",
                retryable=False,
            )
        return media_path, "image/png"

    def _message(
        self,
        run: AsyncTaskRun,
        *,
        image_media_present: bool = False,
    ) -> str:
        if self._is_image_task(run):
            if run.status is AsyncRunStatus.COMPLETED:
                if image_media_present:
                    return "Ảnh đã tạo xong."
                return (
                    "Em chưa gửi được ảnh ở lượt này. "
                    "Tác vụ đã kết thúc và không còn xử lý."
                )
            if run.status in {
                AsyncRunStatus.FAILED,
                AsyncRunStatus.BLOCKED,
                AsyncRunStatus.CANCELLED,
            }:
                return (
                    "Em chưa tạo hoặc chỉnh sửa được ảnh ở lượt này. "
                    "Tác vụ đã kết thúc và không còn xử lý. Anh có thể thử lại."
                )

        summary = ""
        artifacts: list[str] = []
        verification: list[str] = []

        if run.result_json:
            try:
                result = json.loads(run.result_json)
            except json.JSONDecodeError:
                result = {}
            if isinstance(result, dict):
                raw_summary = result.get("summary")
                if isinstance(raw_summary, str):
                    summary = raw_summary
                raw_artifacts = result.get("artifacts")
                if isinstance(raw_artifacts, list):
                    artifacts = [
                        str(item) for item in raw_artifacts
                    ]
                raw_verification = result.get("verification")
                if isinstance(raw_verification, list):
                    verification = [
                        str(item) for item in raw_verification
                    ]

        lines = [summary or run.last_error_message or "No summary."]
        if verification:
            lines.extend(
                ["", "Verification:", *verification[:10]]
            )
        if artifacts:
            lines.extend(["", "Artifacts:", *artifacts[:10]])

        return "\n".join(lines)[:4000]

    @staticmethod
    def _is_image_task(run: AsyncTaskRun) -> bool:
        result: dict[str, object] = {}
        if run.result_json:
            try:
                parsed_result = json.loads(run.result_json)
            except json.JSONDecodeError:
                parsed_result = {}
            if isinstance(parsed_result, dict):
                result = parsed_result

        if result.get("profile") == _IMAGE_PROFILE:
            return True
        artifacts = result.get("artifacts")
        if isinstance(artifacts, dict) and isinstance(artifacts.get("image"), dict):
            return True

        request: dict[str, object] = {}
        if run.request_json:
            try:
                parsed_request = json.loads(run.request_json)
            except json.JSONDecodeError:
                parsed_request = {}
            if isinstance(parsed_request, dict):
                request = parsed_request

        if isinstance(request.get("reference_image"), str) and request["reference_image"]:
            return True

        raw_constraints = request.get("constraints")
        if isinstance(raw_constraints, list):
            constraints = {
                item for item in raw_constraints if isinstance(item, str)
            }
            if _IMAGE_TASK_CONSTRAINTS.issubset(constraints):
                return True

        goal = request.get("goal") if isinstance(request.get("goal"), str) else run.goal
        if not isinstance(goal, str) or not goal.strip():
            return False
        route = FastRouter().route(goal)
        capability = CapabilityRouter().route(route, goal)
        return capability.capability is CapabilityKind.VISUAL_IMAGE_GENERATE

    def _http_error(
        self,
        response: httpx.Response,
    ) -> OpenClawTransportError:
        status = response.status_code
        if status in {408, 504}:
            code = "gateway_timeout"
            retryable = True
        elif status == 429:
            code = "rate_limited"
            retryable = True
        elif status in {502, 503}:
            code = "gateway_unavailable"
            retryable = True
        elif status in {401, 403}:
            code = "authentication_error"
            retryable = False
        else:
            code = "notification_contract_error"
            retryable = status >= 500

        try:
            body = response.json()
        except ValueError:
            body = response.text[:2000]

        return OpenClawTransportError(
            code,
            str(self.redactor.redact(body))[:2000],
            retryable=retryable,
            status_code=status,
        )
