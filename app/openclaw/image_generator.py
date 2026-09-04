from __future__ import annotations

import asyncio
import hashlib
import re
import struct
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from app.openclaw.models import OpenClawTransportError

_IMAGE_MODEL = "openai/gpt-image-2"
_IMAGE_PROVIDER = "openai"
_IMAGE_MODEL_ID = "gpt-image-2"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_IMAGE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}(?:---[0-9a-f-]{36})?\.png$")


@dataclass(frozen=True)
class OpenClawImageArtifact:
    path: Path
    media_path: str
    sha256: str
    mime_type: str
    size_bytes: int
    width: int
    height: int
    provider: str
    model: str
    requested_aspect_ratio: str
    rendered_size: str
    recovered: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "media_path": self.media_path,
            "sha256": self.sha256,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
            "provider": self.provider,
            "model": self.model,
            "requested_aspect_ratio": self.requested_aspect_ratio,
            "rendered_size": self.rendered_size,
            "recovered": self.recovered,
        }


class OpenClawImageGenerator:
    """One-shot, verified wrapper around OpenClaw's native image tool."""

    def __init__(
        self,
        *,
        base_url: str,
        invoke_path: str = "/tools/invoke",
        host_output_root: Path,
        container_output_root: str,
        auth_token: str | None = None,
        model: str = _IMAGE_MODEL,
        timeout_seconds: float = 600.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if model != _IMAGE_MODEL:
            raise ValueError(f"Only the pinned image model is allowed: {_IMAGE_MODEL}")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not base_url.strip():
            raise ValueError("base_url cannot be blank")
        if not invoke_path.strip():
            raise ValueError("invoke_path cannot be blank")
        if not container_output_root.strip() or not container_output_root.startswith("/"):
            raise ValueError("container_output_root must be an absolute POSIX path")
        self.base_url = base_url.rstrip("/")
        self.invoke_path = "/" + invoke_path.lstrip("/")
        self.host_output_root = host_output_root
        self.container_output_root = container_output_root.rstrip("/")
        self.auth_token = auth_token
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def _require_subscription_route_ready(self, run_id: str) -> None:
        catalog = await self._read_subscription_route_catalog(run_id)
        self._validate_subscription_route_catalog(catalog)

    async def _read_subscription_route_catalog(self, run_id: str) -> dict[str, Any]:
        payload = {
            "name": "image_generate",
            "args": {"action": "list"},
            "sessionKey": self._sync_session_key(run_id),
        }
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=min(self.timeout_seconds, 5.0),
                transport=self.transport,
            ) as client:
                response = await client.post(self.invoke_path, headers=headers, json=payload)
        except (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.HTTPError,
        ) as error:
            raise self._error(
                "image_subscription_route_probe_unavailable",
                "Could not verify the managed OpenClaw image route.",
                retryable=True,
            ) from error
        if response.status_code >= 400:
            raise self._error(
                "image_subscription_route_probe_unavailable",
                "Managed OpenClaw image route catalog was unavailable.",
                retryable=True,
            )
        try:
            body = response.json()
        except ValueError as error:
            raise self._error(
                "image_subscription_route_probe_invalid",
                "Managed OpenClaw image route catalog returned invalid JSON.",
            ) from error
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise self._subscription_route_error()
        result = body.get("result")
        details = result.get("details") if isinstance(result, dict) else None
        if not isinstance(details, dict):
            raise self._subscription_route_error()
        return details

    @staticmethod
    def _validate_subscription_route_catalog(catalog: Any) -> None:
        if not isinstance(catalog, dict):
            raise OpenClawImageGenerator._subscription_route_error()
        providers = catalog.get("providers")
        if not isinstance(providers, list):
            raise OpenClawImageGenerator._subscription_route_error()
        openai_rows = [
            row
            for row in providers
            if isinstance(row, dict) and row.get("id") == _IMAGE_PROVIDER
        ]
        if len(openai_rows) != 1:
            raise OpenClawImageGenerator._subscription_route_error()
        provider = openai_rows[0]
        models = provider.get("models")
        if provider.get("configured") is not True:
            raise OpenClawImageGenerator._subscription_route_error()
        if "selected" in provider and provider.get("selected") is not True:
            raise OpenClawImageGenerator._subscription_route_error()
        if provider.get("defaultModel") != _IMAGE_MODEL_ID:
            raise OpenClawImageGenerator._subscription_route_error()
        if not isinstance(models, list) or _IMAGE_MODEL_ID not in models:
            raise OpenClawImageGenerator._subscription_route_error()

    @staticmethod
    def _subscription_route_error() -> OpenClawTransportError:
        return OpenClawTransportError(
            "image_subscription_route_unverified",
            "Managed OpenClaw subscription image route is not ready.",
            retryable=False,
            uncertain_side_effect=False,
        )

    async def generate(
        self,
        *,
        prompt: str,
        run_id: str,
        aspect_ratio: str = "",
    ) -> OpenClawImageArtifact:
        if not prompt.strip():
            raise self._error("image_prompt_empty", "Image prompt cannot be blank.")
        self._validate_run_id(run_id)

        existing = self._existing_artifact(run_id)
        if existing is not None:
            host_path, media_path = self._paths_from_host(existing, run_id)
            return self._verify(
                host_path,
                media_path,
                aspect_ratio,
                recovered=True,
                provider=_IMAGE_PROVIDER,
                model=_IMAGE_MODEL_ID,
            )

        await self._require_subscription_route_ready(run_id)
        self.host_output_root.mkdir(parents=True, exist_ok=True)

        size = self._render_size(aspect_ratio)
        idempotency_key = f"visual-image:{run_id}"
        payload: dict[str, Any] = {
            "name": "image_generate",
            "args": {
                "prompt": prompt,
                "model": self.model,
                "count": 1,
                "size": size,
                "quality": "high",
                "outputFormat": "png",
                "filename": f"{run_id}.png",
                "timeoutMs": int(self.timeout_seconds * 1000),
            },
            # OpenClaw 2026.7.1 may detach this native media task. Core waits
            # for the managed artifact below; the Telegram session remains owned
            # by Core and notifier.
            "sessionKey": self._sync_session_key(run_id),
            "idempotencyKey": idempotency_key,
        }
        if aspect_ratio:
            payload["args"]["aspectRatio"] = aspect_ratio

        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        deadline = time.monotonic() + self.timeout_seconds
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self.invoke_path,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as error:
            existing = self._existing_artifact(run_id)
            if existing is not None:
                host_path, media_path = self._paths_from_host(existing, run_id)
                return self._verify(
                    host_path,
                    media_path,
                    aspect_ratio,
                    recovered=True,
                    provider=_IMAGE_PROVIDER,
                    model=_IMAGE_MODEL_ID,
                )
            raise self._error(
                "image_generation_timeout",
                "Native image generation timed out; outcome is uncertain.",
                uncertain=True,
            ) from error
        except httpx.ConnectError as error:
            raise self._error(
                "image_generation_unavailable",
                "Native OpenClaw image tool is unavailable.",
                retryable=True,
            ) from error
        except httpx.RemoteProtocolError as error:
            existing = self._existing_artifact(run_id)
            if existing is not None:
                host_path, media_path = self._paths_from_host(existing, run_id)
                return self._verify(
                    host_path,
                    media_path,
                    aspect_ratio,
                    recovered=True,
                    provider=_IMAGE_PROVIDER,
                    model=_IMAGE_MODEL_ID,
                )
            raise self._error(
                "image_transport_error",
                "Native OpenClaw image request failed after dispatch; outcome is uncertain.",
                retryable=True,
                uncertain=True,
            ) from error
        except httpx.HTTPError as error:
            raise self._error(
                "image_transport_error",
                "Native OpenClaw image request failed.",
                retryable=True,
            ) from error

        if response.status_code >= 400:
            existing = self._existing_artifact(run_id)
            if existing is not None:
                host_path, media_path = self._paths_from_host(existing, run_id)
                return self._verify(
                    host_path,
                    media_path,
                    aspect_ratio,
                    recovered=True,
                    provider=_IMAGE_PROVIDER,
                    model=_IMAGE_MODEL_ID,
                )
            raise self._http_error(response)
        try:
            body = response.json()
        except ValueError as error:
            raise self._error(
                "image_invalid_response",
                "Native image tool returned invalid JSON.",
            ) from error

        metadata = self._parse_response(body, run_id)
        if metadata.get("async") is True:
            return await self._wait_for_async_artifact(
                run_id=run_id,
                aspect_ratio=aspect_ratio,
                provider=metadata["provider"],
                model=metadata["model"],
                deadline=deadline,
            )

        media_path = metadata.get("media_path")
        if not isinstance(media_path, str) or not media_path:
            raise self._error(
                "image_output_missing",
                "Native image tool returned no managed image path.",
                uncertain=True,
            )
        host_path, media_path = self._map_response_path(media_path, run_id)
        if not host_path.exists():
            existing = self._existing_artifact(run_id)
            if existing is not None:
                host_path, media_path = self._paths_from_host(existing, run_id)
                return self._verify(
                    host_path,
                    media_path,
                    aspect_ratio,
                    recovered=True,
                    provider=metadata["provider"],
                    model=metadata["model"],
                )
        return self._verify(
            host_path,
            media_path,
            aspect_ratio,
            recovered=False,
            metadata=metadata,
            provider=metadata["provider"],
            model=metadata["model"],
        )

    async def _wait_for_async_artifact(
        self,
        *,
        run_id: str,
        aspect_ratio: str,
        provider: str,
        model: str,
        deadline: float,
    ) -> OpenClawImageArtifact:
        while True:
            existing = self._existing_artifact(run_id)
            if existing is not None:
                host_path, media_path = self._paths_from_host(existing, run_id)
                return self._verify(
                    host_path,
                    media_path,
                    aspect_ratio,
                    recovered=True,
                    provider=provider,
                    model=model,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(0.5, remaining))
        raise self._error(
            "image_generation_timeout",
            "Native image task did not publish a verified artifact before the deadline.",
            uncertain=True,
        )

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if _RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise OpenClawTransportError(
                "image_run_id_invalid",
                "Image run identity is invalid.",
                retryable=False,
            )

    @staticmethod
    def _sync_session_key(run_id: str) -> str:
        return f"agent:main:cron:anh-duong-image:run:{run_id}"

    def _existing_artifact(self, run_id: str) -> Path | None:
        try:
            root = self.host_output_root.resolve(strict=False)
            candidates = sorted(
                path
                for path in (
                    list(root.glob(f"{run_id}.png"))
                    + list(root.glob(f"{run_id}---*.png"))
                )
                if path.exists()
            )
        except OSError as error:
            raise self._error(
                "image_artifact_root_unavailable",
                "Managed image output root is not accessible.",
            ) from error
        if len(candidates) > 1:
            raise self._error(
                "image_artifact_ambiguous",
                "More than one native image artifact matches this run.",
            )
        return candidates[0] if candidates else None

    def _paths_from_host(self, host_path: Path, run_id: str) -> tuple[Path, str]:
        root = self.host_output_root.resolve(strict=False)
        resolved = host_path.resolve(strict=False)
        try:
            relative = resolved.relative_to(root)
        except ValueError as error:
            raise self._error("image_path_escape", "Image output path escaped its root.") from error
        if relative.name not in {f"{run_id}.png"} and not relative.name.startswith(f"{run_id}---"):
            raise self._error(
                "image_output_mismatch", "Native image filename does not match the run."
            )
        media_path = f"{self.container_output_root}/{relative.as_posix()}"
        return resolved, media_path

    def _map_response_path(self, media_path: str, run_id: str) -> tuple[Path, str]:
        if not isinstance(media_path, str) or not media_path.startswith("/"):
            raise self._error("image_output_mismatch", "Native image path is invalid.")
        root = PurePosixPath(self.container_output_root)
        candidate = PurePosixPath(media_path)
        try:
            relative = candidate.relative_to(root)
        except ValueError as error:
            raise self._error(
                "image_path_escape",
                "Native image path is outside the managed output root.",
            ) from error
        if len(relative.parts) != 1 or _IMAGE_FILENAME_PATTERN.fullmatch(relative.name) is None:
            raise self._error("image_output_mismatch", "Native image filename is invalid.")
        if relative.name != f"{run_id}.png" and not relative.name.startswith(f"{run_id}---"):
            raise self._error(
                "image_output_mismatch", "Native image filename does not match the run."
            )
        host_path = self.host_output_root.resolve(strict=False) / relative.name
        return host_path, media_path

    @staticmethod
    def _render_size(aspect_ratio: str) -> str:
        return {
            "": "1024x1024",
            "1:1": "1024x1024",
            "4:5": "1024x1280",
            "5:4": "1280x1024",
            "9:16": "1024x1536",
            "16:9": "1536x1024",
            "3:4": "1024x1365",
            "4:3": "1365x1024",
        }.get(aspect_ratio, "1024x1024")

    def _parse_response(self, body: Any, run_id: str) -> dict[str, Any]:
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise self._error(
                "image_generation_failed",
                "Native image tool did not report success.",
                uncertain=True,
            )
        result = body.get("result")
        if not isinstance(result, dict):
            raise self._error(
                "image_invalid_response",
                "Native image tool result is not an object.",
                uncertain=True,
            )
        details = result.get("details")
        if not isinstance(details, dict):
            details = result

        status = str(details.get("status", "")).strip().casefold()
        provider = self._required_string(
            details.get("provider", _IMAGE_PROVIDER), "image_provider_missing"
        )
        model = self._required_string(details.get("model", _IMAGE_MODEL_ID), "image_model_missing")
        if provider != _IMAGE_PROVIDER or model not in {_IMAGE_MODEL, _IMAGE_MODEL_ID}:
            raise self._error(
                "image_provider_mismatch",
                "Native provider or model was not pinned.",
            )
        if "attempts" in details:
            attempts = details.get("attempts")
            if not isinstance(attempts, list) or attempts:
                raise self._error(
                    "image_fallback_forbidden",
                    "Native image generation attempted a fallback route.",
                )
        if details.get("async") is True or status in {"started", "pending", "running"}:
            return {
                "async": True,
                "provider": provider,
                "model": _IMAGE_MODEL_ID if model == _IMAGE_MODEL else model,
            }
        count = details.get("count")
        if count not in (1, "1"):
            raise self._error(
                "image_count_mismatch",
                "Native image tool did not return exactly one image.",
            )
        paths = details.get("paths")
        if not isinstance(paths, list):
            media = details.get("media")
            paths = media.get("mediaUrls") if isinstance(media, dict) else None
        if not isinstance(paths, list) or len(paths) != 1:
            attachments = details.get("attachments")
            if not isinstance(attachments, list):
                media = details.get("media")
                attachments = media.get("attachments") if isinstance(media, dict) else None
            if (
                isinstance(attachments, list)
                and len(attachments) == 1
                and isinstance(attachments[0], dict)
            ):
                paths = [attachments[0].get("path")]
            else:
                paths = []
        media_path = paths[0] if paths and isinstance(paths[0], str) else ""
        if not media_path:
            raise self._error(
                "image_output_missing",
                "Native image tool returned no managed image path.",
                uncertain=True,
            )
        attachments = details.get("attachments")
        if not isinstance(attachments, list):
            media = details.get("media")
            attachments = media.get("attachments") if isinstance(media, dict) else None
        attachment = (
            attachments[0]
            if isinstance(attachments, list)
            and len(attachments) == 1
            and isinstance(attachments[0], dict)
            else {}
        )
        mime_type = attachment.get("mimeType")
        if mime_type not in (None, "image/png"):
            raise self._error("image_output_mismatch", "Native image MIME type was not PNG.")
        metadata: dict[str, Any] = {
            "media_path": media_path,
            "provider": provider,
            "model": _IMAGE_MODEL_ID if model == _IMAGE_MODEL else model,
            "mime_type": mime_type or "image/png",
        }
        for key in ("size", "width", "height"):
            if key in attachment:
                metadata[key] = attachment[key]
            elif key in details:
                metadata[key] = details[key]
        return metadata

    @staticmethod
    def _required_string(value: Any, code: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise OpenClawTransportError(code, "Native image metadata is missing.", retryable=False)
        return value.strip()

    def _verify(
        self,
        host_path: Path,
        media_path: str,
        aspect_ratio: str,
        *,
        recovered: bool,
        provider: str,
        model: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> OpenClawImageArtifact:
        root = self.host_output_root.resolve(strict=False)
        resolved = host_path.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise self._error("image_path_escape", "Image output path escaped its root.") from error
        if host_path.is_symlink() or not host_path.is_file():
            raise self._error("image_artifact_missing", "Verified image artifact is missing.")
        data = host_path.read_bytes()
        width, height = self._png_dimensions(data)
        if metadata is not None:
            if metadata.get("mime_type") not in (None, "image/png"):
                raise self._error("image_output_mismatch", "Verified image MIME type was not PNG.")
            if metadata.get("size") not in (None, len(data), str(len(data))):
                raise self._error(
                    "image_size_mismatch",
                    "Native image size metadata mismatched the artifact.",
                )
            if metadata.get("width") not in (None, width, str(width)) or metadata.get(
                "height"
            ) not in (None, height, str(height)):
                raise self._error(
                    "image_dimensions_mismatch",
                    "Native image dimensions mismatched the artifact.",
                )
        return OpenClawImageArtifact(
            path=resolved,
            media_path=media_path,
            sha256=hashlib.sha256(data).hexdigest(),
            mime_type="image/png",
            size_bytes=len(data),
            width=width,
            height=height,
            provider=provider,
            model=model,
            requested_aspect_ratio=aspect_ratio,
            rendered_size=f"{width}x{height}",
            recovered=recovered,
        )

    @staticmethod
    def _png_dimensions(data: bytes) -> tuple[int, int]:
        if len(data) < 24 or data[:8] != _PNG_SIGNATURE:
            raise OpenClawImageGenerator._error(
                "image_invalid_png",
                "Image artifact is not a valid PNG.",
            )
        length = struct.unpack(">I", data[8:12])[0]
        if length != 13 or data[12:16] != b"IHDR":
            raise OpenClawImageGenerator._error(
                "image_invalid_png",
                "PNG IHDR is missing or malformed.",
            )
        width, height = struct.unpack(">II", data[16:24])
        if width <= 0 or height <= 0:
            raise OpenClawImageGenerator._error(
                "image_invalid_png",
                "PNG dimensions are invalid.",
            )
        return width, height

    @staticmethod
    def _http_error(response: httpx.Response) -> OpenClawTransportError:
        status = response.status_code
        if status in {408, 504}:
            code, retryable = "image_gateway_timeout", True
        elif status == 429:
            code, retryable = "image_rate_limited", True
        elif status in {502, 503}:
            code, retryable = "image_gateway_unavailable", True
        elif status in {400, 401, 403, 404, 405, 422}:
            code, retryable = "image_contract_error", False
        else:
            code, retryable = "image_gateway_error", status >= 500
        return OpenClawTransportError(
            code,
            f"Native image tool returned HTTP {status}.",
            retryable=retryable,
            uncertain_side_effect=status >= 408 or status >= 500,
            status_code=status,
        )

    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        retryable: bool = False,
        uncertain: bool = False,
    ) -> OpenClawTransportError:
        return OpenClawTransportError(
            code,
            message,
            retryable=retryable,
            uncertain_side_effect=uncertain,
        )
