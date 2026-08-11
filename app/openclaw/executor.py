from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

import httpx
from pydantic import ValidationError

from app.audit import SecretRedactor
from app.openclaw.models import (
    OpenClawExecutionRequest,
    OpenClawExecutionResult,
    OpenClawTransportError,
)


class OpenClawExecutor:
    _HOST_WORKSPACE = PurePosixPath("/mnt/f/AIOS/anh-duong-core")
    _GATEWAY_WORKSPACE = PurePosixPath("/workspaces/anh-duong-core")

    def __init__(
        self,
        *,
        base_url: str,
        execution_path: str = "/v1/responses",
        auth_token: str | None = None,
        timeout_seconds: float = 600.0,
        transport: httpx.AsyncBaseTransport | None = None,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.execution_path = "/" + execution_path.lstrip("/")
        self.auth_token = auth_token
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.redactor = redactor or SecretRedactor()

    async def execute(
        self,
        request: OpenClawExecutionRequest,
    ) -> OpenClawExecutionResult:
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": request.idempotency_key,
        }
        if self.auth_token:
            headers["Authorization"] = (
                f"Bearer {self.auth_token}"
            )

        gateway_request = request.model_copy(
            update={"workspace": self._gateway_workspace(request.workspace)}
        )

        payload = {
            "model": "openclaw/default",
            "user": f"async:{request.task_id}",
            "instructions": (
                "Execute the supplied task within its workspace and "
                "constraints. Return JSON with outcome, summary, "
                "artifacts, and verification."
            ),
            "input": json.dumps(
                gateway_request.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self.execution_path,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as error:
            raise OpenClawTransportError(
                "timeout",
                "OpenClaw request timed out.",
                retryable=False,
                uncertain_side_effect=True,
            ) from error
        except httpx.ConnectError as error:
            raise OpenClawTransportError(
                "connection_error",
                "OpenClaw connection failed.",
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
                "OpenClaw returned invalid JSON.",
                retryable=False,
                status_code=response.status_code,
            ) from error

        output_text = self._extract_output_text(body)
        result_payload = self._parse_result_payload(output_text)
        if result_payload.get("outcome") == "success":
            result_payload["outcome"] = "completed"
        external_run_id = body.get("id")
        if isinstance(external_run_id, str):
            result_payload["external_run_id"] = external_run_id

        try:
            return OpenClawExecutionResult.model_validate(result_payload)
        except ValidationError as error:
            raise OpenClawTransportError(
                "invalid_response_contract",
                "OpenClaw returned an invalid execution result contract.",
                retryable=False,
                uncertain_side_effect=False,
                status_code=response.status_code,
            ) from error

    @classmethod
    def _gateway_workspace(cls, workspace: str | None) -> str | None:
        if workspace is None:
            return None
        path = PurePosixPath(workspace)
        try:
            relative = path.relative_to(cls._HOST_WORKSPACE)
        except ValueError:
            return workspace
        return str(cls._GATEWAY_WORKSPACE / relative)

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
        elif status in {400, 404, 405, 422}:
            code = "contract_error"
            retryable = False
        else:
            code = "gateway_error"
            retryable = status >= 500

        message = self._response_error_message(response)
        return OpenClawTransportError(
            code,
            message,
            retryable=retryable,
            status_code=status,
        )

    def _response_error_message(
        self,
        response: httpx.Response,
    ) -> str:
        try:
            body = response.json()
        except ValueError:
            body = response.text[:2000]
        return str(self.redactor.redact(body))[:2000]

    @staticmethod
    def _extract_output_text(body: Any) -> str:
        if not isinstance(body, dict):
            raise OpenClawTransportError(
                "invalid_response",
                "OpenClaw response must be an object.",
                retryable=False,
            )

        output = body.get("output")
        if not isinstance(output, list):
            raise OpenClawTransportError(
                "invalid_response",
                "OpenClaw response has no output list.",
                retryable=False,
            )

        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "output_text"
                    and isinstance(part.get("text"), str)
                ):
                    texts.append(part["text"])

        if not texts:
            raise OpenClawTransportError(
                "invalid_response",
                "OpenClaw response contains no output text.",
                retryable=False,
            )
        return "\n".join(texts).strip()

    @staticmethod
    def _parse_result_payload(text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {
                "outcome": "completed",
                "summary": text,
                "artifacts": [],
                "verification": [],
            }

        if not isinstance(parsed, dict):
            raise OpenClawTransportError(
                "invalid_response",
                "Structured result must be a JSON object.",
                retryable=False,
            )
        return parsed
