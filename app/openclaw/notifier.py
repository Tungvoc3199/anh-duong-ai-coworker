from __future__ import annotations

import json

import httpx

from app.async_tasks.models import (
    AsyncRunStatus,
    AsyncTaskRun,
)
from app.audit import SecretRedactor
from app.openclaw.models import OpenClawTransportError

TERMINAL_RUN_STATUSES = {
    AsyncRunStatus.COMPLETED,
    AsyncRunStatus.FAILED,
    AsyncRunStatus.BLOCKED,
    AsyncRunStatus.CANCELLED,
}


class OpenClawNotifier:
    def __init__(
        self,
        *,
        base_url: str,
        notification_path: str = "/tools/invoke",
        auth_token: str | None = None,
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
        payload = {
            "tool": "message",
            "args": {
                "action": "send",
                "channel": "telegram",
                "target": run.source_chat_id,
                "message": self._message(run),
                "idempotencyKey": idempotency_key,
            },
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

    def _message(self, run: AsyncTaskRun) -> str:
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
