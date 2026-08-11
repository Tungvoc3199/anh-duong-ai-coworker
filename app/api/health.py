from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/ready")
def ready(request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "database": "not_initialized"},
        )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "database": "error"},
        ) from exc
    return {"status": "ready", "database": "ok"}
