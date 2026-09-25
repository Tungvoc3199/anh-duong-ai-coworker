from __future__ import annotations

from typing import Any

import httpx


def _status_artifact(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = {}
    artifact = dict(payload) if isinstance(payload, dict) else {}
    artifact["http_status"] = response.status_code
    artifact.setdefault("status", "unknown")
    return artifact


async def probe_core_status_with_client(client: Any) -> dict[str, Any]:
    health = await _probe_endpoint(client, "/health")
    ready = await _probe_endpoint(client, "/ready")
    if "http_status" in health:
        service = {"status": "running", "evidence": "core_asgi:/health"}
    elif "http_status" in ready:
        service = {"status": "running", "evidence": "core_asgi:/ready"}
    else:
        service = {"status": "unavailable", "evidence": "core_asgi:no_response"}
    return {"service": service, "health": health, "ready": ready}


async def _probe_endpoint(client: Any, path: str) -> dict[str, Any]:
    try:
        response = await client.get(path)
    except httpx.HTTPError:
        return {"status": "unavailable"}
    return _status_artifact(response)


async def probe_core_status_via_asgi(app: Any) -> dict[str, Any]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://anh-duong-core.internal",
        timeout=5.0,
    ) as client:
        return await probe_core_status_with_client(client)
