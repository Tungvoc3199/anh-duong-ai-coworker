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
    _COMPLETED_OUTCOMES = {
        "completed",
        "success",
        "succeeded",
        "done",
        "ok",
    }
    _BLOCKED_OUTCOMES = {
        "blocked",
        "approval_required",
        "requires_approval",
        "needs_approval",
        "pending_approval",
    }
    _FAILED_OUTCOMES = {
        "failed",
        "failure",
        "error",
        "errored",
    }
    _SUMMARY_KEYS = (
        "summary",
        "answer",
        "final_answer",
        "message",
        "response",
        "text",
        "content",
    )

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
            headers["Authorization"] = f"Bearer {self.auth_token}"

        gateway_request = request.model_copy(
            update={"workspace": self._gateway_workspace(request.workspace)}
        )

        payload = {
            "model": "openclaw/default",
            "user": f"async:{request.task_id}",
            "instructions": (
                "Execute the supplied task within its workspace and constraints. "
                "Always return a final user-facing answer. If returning JSON, "
                "include outcome (completed|blocked|failed) and a non-empty "
                "summary; artifacts and verification are optional."
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
        result_payload = self._normalize_result_payload(
            result_payload,
            output_text=output_text,
        )
        external_run_id = body.get("id")
        if isinstance(external_run_id, str):
            result_payload["external_run_id"] = external_run_id

        try:
            return OpenClawExecutionResult.model_validate(result_payload)
        except ValidationError:
            return OpenClawExecutionResult(
                outcome="failed",
                summary=self._normalize_summary(
                    result_payload,
                    output_text=output_text,
                ),
                error_code="result_contract_normalization_failed",
                external_run_id=(
                    external_run_id
                    if isinstance(external_run_id, str)
                    else None
                ),
            )

    def _normalize_result_payload(
        self,
        payload: dict[str, Any],
        *,
        output_text: str,
    ) -> dict[str, Any]:
        normalized = dict(payload)
        nested_result = normalized.get("result")
        if isinstance(nested_result, dict):
            for key, value in nested_result.items():
                normalized.setdefault(key, value)

        normalized["outcome"] = self._normalize_outcome(normalized)
        normalized["summary"] = self._normalize_summary(
            normalized,
            output_text=output_text,
        )
        normalized["artifacts"] = self._normalize_detail_field(
            normalized.get("artifacts")
        )
        normalized["verification"] = self._normalize_detail_field(
            normalized.get("verification")
        )
        normalized["files_changed"] = self._normalize_string_items(
            normalized.get("files_changed")
        )
        normalized["commands_run"] = self._normalize_string_items(
            normalized.get("commands_run")
        )
        normalized["tests"] = self._normalize_tests(normalized.get("tests"))
        normalized["duration_ms"] = self._normalize_duration_ms(
            normalized.get("duration_ms")
        )
        for key in ("model", "provider", "profile", "error_code"):
            value = normalized.get(key)
            if value is not None and not isinstance(value, str):
                normalized[key] = str(value)
        return normalized

    def _normalize_outcome(self, payload: dict[str, Any]) -> str:
        raw_outcome: object = payload.get("outcome")
        if not isinstance(raw_outcome, str):
            raw_outcome = payload.get("status")
        if not isinstance(raw_outcome, str):
            raw_outcome = payload.get("state")

        explicit_outcome = isinstance(raw_outcome, str)
        if explicit_outcome:
            value = raw_outcome.strip().casefold().replace("-", "_")
            if value in self._COMPLETED_OUTCOMES:
                return "completed"
            if value in self._BLOCKED_OUTCOMES:
                return "blocked"
            if value in self._FAILED_OUTCOMES:
                return "failed"

        if payload.get("approval_required") is True:
            return "blocked"
        if payload.get("requires_approval") is True:
            return "blocked"
        if payload.get("error") not in (None, "", False):
            return "failed"
        if payload.get("error_code") not in (None, ""):
            return "failed"
        if explicit_outcome:
            return "failed"
        return "completed"

    def _normalize_summary(
        self,
        payload: dict[str, Any],
        *,
        output_text: str,
    ) -> str:
        for key in self._SUMMARY_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return str(self.redactor.redact(value.strip()))

        nested_result = payload.get("result")
        if isinstance(nested_result, dict):
            for key in self._SUMMARY_KEYS:
                value = nested_result.get(key)
                if isinstance(value, str) and value.strip():
                    return str(self.redactor.redact(value.strip()))
        elif isinstance(nested_result, str) and nested_result.strip():
            return str(self.redactor.redact(nested_result.strip()))

        redacted = self.redactor.redact(payload)
        try:
            fallback = json.dumps(
                redacted,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError):
            fallback = output_text
        return str(self.redactor.redact(fallback)).strip() or "Đã xử lý yêu cầu."

    @staticmethod
    def _normalize_detail_field(value: object) -> object:
        if value is None:
            return ()
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return (value,)
        if isinstance(value, (list, tuple)):
            if all(isinstance(item, str) for item in value):
                return tuple(value)
            return {"items": list(value)}
        return {"value": value}

    @staticmethod
    def _normalize_string_items(value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, (list, tuple)):
            return tuple(str(item) for item in value if item is not None)
        return (str(value),)

    @staticmethod
    def _normalize_tests(value: object) -> tuple[dict[str, Any], ...]:
        if value is None:
            return ()
        if isinstance(value, dict):
            return (value,)
        if isinstance(value, (list, tuple)):
            normalized: list[dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    normalized.append(item)
                else:
                    normalized.append({"result": str(item)})
            return tuple(normalized)
        return ({"result": str(value)},)

    @staticmethod
    def _normalize_duration_ms(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, float):
            return int(value) if value >= 0 else None
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
        return None

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

        if isinstance(parsed, dict):
            return parsed
        return {
            "outcome": "completed",
            "summary": text,
            "artifacts": [],
            "verification": [],
        }
