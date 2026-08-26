from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any, overload

import httpx
from pydantic import ValidationError

from app.audit import SecretRedactor
from app.openclaw.models import (
    OpenClawExecutionRequest,
    OpenClawExecutionResult,
    OpenClawTransportError,
)
from app.orchestration.coding_governance import (
    CodingAssignment,
    CodingResultContract,
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
        "blocked_at_safe_gate",
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

    # Absolute paths and shell commands inside the *operator's* runtime
    # (host/WSL/Docker layer) are operational facts. They may appear in a
    # response ONLY if they were verified by tool output produced within THIS
    # request. Historical instruction files (AGENTS.md, TOOLS.md, USER.md,
    # SOUL.md, MEMORY.md and any skill/plugin docs) and past session memories
    # are NOT fresh evidence and must never be quoted as operational facts.
    _RUNTIME_EVIDENCE_POLICY = (
        "Runtime evidence rule: any file path, directory, CLI command or "
        "shell command that refers to the operator's host/WSL/Docker "
        "environment must come exclusively from tool output gathered during "
        "this same request (e.g. `ls`, `pwd`, `which`, `docker inspect`, "
        "`docker ps`). Never copy paths or commands from "
        "AGENTS.md, TOOLS.md, USER.md, SOUL.md, MEMORY.md, skill files, "
        "prior session history, or model memory -- those are historical and "
        "may be wrong for the current runtime. If you did not verify a path "
        "or command with fresh tool output in this request, do not include "
        "it; say the information is not known for the current runtime "
        "instead of guessing or inventing an example command or path."
    )
    # Definitely stale/unverifiable runtime anchors. Any occurrence in a
    # response is replaced with the UNKNOWN marker (see
    # _guard_operational_evidence). Kept in one place for tests.
    _UNVERIFIED_RUNTIME_ANCHORS = (
        # /mnt/f/AIOS/openclaw does not exist in the current runtime:
        # the compose project lives at /home/thadc/AIOS/openclaw.
        "/mnt/f/AIOS/openclaw",
        # Windows-style duplicates of the same stale pointer.
        "F:/AIOS/openclaw",
        "F:\\AIOS\\openclaw",
    )
    _UNVERIFIED_RUNTIME_REF = "UNKNOWN"

    def _instructions(self) -> str:
        return (
            "Execute the supplied task within its workspace and constraints. "
            "Always return a final user-facing answer. If returning JSON, "
            "include outcome (completed|blocked|failed) and a non-empty "
            "summary; artifacts and verification are optional. "
            + self._RUNTIME_EVIDENCE_POLICY
        )

    def _governed_instructions(
        self,
        assignment: CodingAssignment,
        *,
        mapped_workspace: str,
    ) -> str:
        return (
            f"{self._instructions()} GOVERNED CODING REQUIREMENTS: Work only "
            f"in the exact mapped workspace `{mapped_workspace}`. Your first "
            "action must use a fresh tool call to run `pwd`; its output must "
            f"equal `{mapped_workspace}` exactly. Validate with fresh tool "
            "evidence that this directory is an isolated git worktree before "
            "making changes. Never fall back to $OPENCLAW_HOME, "
            "/home/node/.openclaw/workspace, or any default workspace. If the "
            "exact workspace is inaccessible, `pwd` differs, or isolated "
            "worktree validation fails, return outcome `blocked` without "
            "changing files. Restrict every changed file to these "
            f"repository-relative allowed_paths: {assignment.allowed_paths!r}. "
            "Use real file operations and real commands/tests, and report "
            "their evidence; do not claim evidence that tools did not produce. "
            "Do not write to production, restart services, or write to any "
            "database. Your entire final response must be exactly one bare "
            "JSON object and nothing else: the first non-whitespace character "
            "must be `{` and the final non-whitespace character must be `}`. "
            "Do not use a Markdown code fence, prose, preamble, epilogue, or "
            "diagnostic text outside that object. Put the user-facing summary "
            "inside the JSON object's `summary` field. For outcome `completed`, "
            "return `outcome`, `summary`, and a complete governance_result "
            "matching this assignment exactly: "
            f"checkpoint_id={assignment.checkpoint_id!r}, "
            f"correlation_id={assignment.correlation_id!r}, "
            f"manifest_digest={assignment.manifest_digest!r}. The complete "
            "CodingResultContract must include checkpoint_id, correlation_id, "
            "status, classification, manifest_digest, files_changed, "
            "commands_run, tests, model, provider, profile, duration_ms, "
            "error_code, production_write, service_restart, database_write, "
            "reviewer_outcome, reviewer_read_only, approval_granted, and "
            "repair_round. When reviewer_required is true, obtain a read-only "
            "reviewer outcome of PASS. Set outcome `completed` only when "
            "governance_result.status is exactly `MERGE_READY`. If any required "
            "evidence cannot be completed truthfully, return exactly one valid "
            "JSON object with outcome `blocked` or `failed`, a non-empty "
            "`summary`, an `error_code`, and only evidence actually obtained; "
            "never fabricate missing evidence or add text outside the object."
        )

    @overload
    def _guard_operational_evidence(self, value: str) -> str: ...

    @overload
    def _guard_operational_evidence(self, value: object) -> object: ...

    def _guard_operational_evidence(
        self,
        value: object,
    ) -> object:
        """Strip stale host-runtime paths/commands from an operational answer.

        Policy: paths/CLI commands for the operator's host/WSL/Docker layer
        may come only from fresh tool evidence produced inside THIS request.
        Historical instruction files (AGENTS.md/TOOLS.md/USER.md/SOUL.md/
        MEMORY.md) and past session history are not evidence and must never
        be quoted. Any response text that references a known-stale anchor
        (e.g. ``/mnt/f/AIOS/openclaw``) is replaced with ``UNKNOWN`` --
        including the surrounding command block -- because by definition the
        referenced path was not verified during this request.
        """
        if isinstance(value, str):
            return self._guard_text(value)
        if isinstance(value, dict):
            return {
                key: (
                    self._guard_operational_evidence(item)
                    if isinstance(item, (str, dict, list, tuple))
                    else item
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            guarded = [
                (
                    self._guard_operational_evidence(item)
                    if isinstance(item, (str, dict, list, tuple))
                    else item
                )
                for item in value
            ]
            return tuple(guarded) if isinstance(value, tuple) else guarded
        return value

    def _guard_text(
        self,
        text: str,
    ) -> str:
        if not any(a in text for a in self._UNVERIFIED_RUNTIME_ANCHORS):
            return text

        lines = text.splitlines()
        if "```" not in "\n".join(lines):
            # Plain text: only the stale anchor itself is replaced.
            for anchor in self._UNVERIFIED_RUNTIME_ANCHORS:
                text = text.replace(
                    anchor,
                    self._UNVERIFIED_RUNTIME_REF,
                )
            return text

        # Drop the entire fenced code block containing a stale anchor.
        guarded: list[str] = []
        fence_state = 0  # 0=outside, 1=inside fenced block
        block_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                fence_state = 1 - fence_state
                block_lines.append(line)
                if fence_state == 0:
                    if any(
                        a in "".join(block_lines)
                        for a in self._UNVERIFIED_RUNTIME_ANCHORS
                    ):
                        guarded.append(self._UNVERIFIED_RUNTIME_REF)
                    else:
                        guarded.extend(block_lines)
                    block_lines = []
                continue
            if fence_state == 1:
                block_lines.append(line)
            else:
                for anchor in self._UNVERIFIED_RUNTIME_ANCHORS:
                    if anchor in line:
                        line = line.replace(
                            anchor,
                            self._UNVERIFIED_RUNTIME_REF,
                        )
                guarded.append(line)
        if block_lines:
            if any(
                a in "".join(block_lines)
                for a in self._UNVERIFIED_RUNTIME_ANCHORS
            ):
                guarded.append(self._UNVERIFIED_RUNTIME_REF)
            else:
                guarded.extend(block_lines)
        return "\n".join(guarded)

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
        effective_ws = (
            request.governed_coding.workspace
            if request.governed_coding is not None and request.governed_coding.workspace
            else request.workspace
        )
        if request.governed_coding is not None:
            mapped_ws = self._gateway_workspace(effective_ws)
            if mapped_ws in {
                "/workspaces/anh-duong-core",
                "/home/thadc/AIOS/anh-duong-core",
                "/mnt/f/AIOS/anh-duong-core",
            }:
                raise OpenClawTransportError(
                    "governance_contract_violation",
                    "Governed coding execution cannot target the production workspace.",
                    retryable=False,
                )

        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": request.idempotency_key,
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        gateway_request = request.model_copy(
            update={"workspace": self._gateway_workspace(effective_ws)}
        )
        instructions = self._instructions()
        if request.governed_coding is not None:
            mapped_workspace = gateway_request.workspace
            if mapped_workspace is None:
                raise OpenClawTransportError(
                    "governance_contract_violation",
                    "Governed coding execution requires a mapped workspace.",
                    retryable=False,
                )
            instructions = self._governed_instructions(
                request.governed_coding,
                mapped_workspace=mapped_workspace,
            )

        payload = {
            "model": "openclaw/default",
            "user": f"async:{request.task_id}",
            "instructions": instructions,
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
        result_payload = self._parse_result_payload(
            output_text,
            governed=request.governed_coding is not None,
        )
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
        normalized["artifacts"] = self._guard_operational_evidence(
            self._normalize_detail_field(normalized.get("artifacts"))
        )
        normalized["verification"] = self._guard_operational_evidence(
            self._normalize_detail_field(normalized.get("verification"))
        )
        normalized["files_changed"] = self._guard_operational_evidence(
            self._normalize_string_items(normalized.get("files_changed"))
        )
        normalized["commands_run"] = self._guard_operational_evidence(
            self._normalize_string_items(normalized.get("commands_run"))
        )
        normalized["tests"] = self._guard_operational_evidence(
            self._normalize_tests(normalized.get("tests"))
        )
        normalized["duration_ms"] = self._normalize_duration_ms(
            normalized.get("duration_ms")
        )
        for key in ("model", "provider", "profile", "error_code"):
            value = normalized.get(key)
            if value is not None and not isinstance(value, str):
                normalized[key] = str(value)

        gov_res = normalized.get("governance_result")
        if isinstance(gov_res, dict):
            try:
                normalized["governance_result"] = CodingResultContract.model_validate(gov_res)
            except ValidationError:
                normalized["governance_result"] = None

        redacted = self.redactor.redact(normalized)
        if isinstance(redacted, dict):
            return redacted
        return normalized

    def _normalize_outcome(self, payload: dict[str, Any]) -> str:
        raw_outcome: object = payload.get("outcome")
        if not isinstance(raw_outcome, str):
            raw_outcome = payload.get("status")
        if not isinstance(raw_outcome, str):
            raw_outcome = payload.get("state")
        # A nested `result` dict from the agent is a stronger signal than a
        # generic top-level status wrapper (e.g. {"status":"completed",
        # "result":{"status":"failed",...}} is a genuine failure).
        nested_result = payload.get("result")
        if isinstance(nested_result, dict):
            nested_outcome: object = nested_result.get("outcome")
            if not isinstance(nested_outcome, str):
                nested_outcome = nested_result.get("status")
            if not isinstance(nested_outcome, str):
                nested_outcome = nested_result.get("state")
            if isinstance(nested_outcome, str):
                raw_outcome = nested_outcome

        outcome_text = raw_outcome if isinstance(raw_outcome, str) else None
        explicit_outcome = outcome_text is not None
        if outcome_text is not None:
            value = outcome_text.strip().casefold().replace("-", "_")
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
                return self._guard_operational_evidence(
                    str(self.redactor.redact(value.strip()))
                )

        nested_result = payload.get("result")
        if isinstance(nested_result, dict):
            for key in self._SUMMARY_KEYS:
                value = nested_result.get(key)
                if isinstance(value, str) and value.strip():
                    return self._guard_operational_evidence(
                        str(self.redactor.redact(value.strip()))
                    )
        elif isinstance(nested_result, str) and nested_result.strip():
            return self._guard_operational_evidence(
                str(self.redactor.redact(nested_result.strip()))
            )

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
        return self._guard_operational_evidence(
            str(self.redactor.redact(fallback)).strip()
        ) or "Đã xử lý yêu cầu."

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
    def _parse_result_payload(
        text: str,
        *,
        governed: bool = False,
    ) -> dict[str, Any]:
        if not governed:
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

        candidate = text.lstrip()
        try:
            parsed, end = json.JSONDecoder().raw_decode(candidate)
        except json.JSONDecodeError:
            return {
                "outcome": "failed",
                "summary": "Governed execution returned malformed output.",
                "error_code": "invalid_response_contract",
            }

        if not isinstance(parsed, dict):
            return {
                "outcome": "failed",
                "summary": "Governed execution result must be a JSON object.",
                "error_code": "invalid_response_contract",
            }
        if candidate[end:].strip():
            return {
                "outcome": "failed",
                "summary": "Governed execution returned trailing diagnostic output.",
                "error_code": "invalid_response_contract",
            }
        return parsed
