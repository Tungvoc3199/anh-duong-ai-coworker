from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from app.api.async_tasks import require_internal_bearer
from app.evaluation import (
    EvaluationTelemetryService,
    GoalTelemetry,
    GoalTelemetryNotFound,
    SystemTelemetry,
)

router = APIRouter(
    prefix="/api/internal/evaluation",
    tags=["internal-evaluation"],
    dependencies=[Depends(require_internal_bearer)],
)


def _session(request: Request) -> Session:
    factory = cast(
        sessionmaker[Session] | None,
        request.app.state.session_factory,
    )
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database session factory is not ready.",
        )
    return factory()


@router.get("/goals/{run_id}", response_model=GoalTelemetry)
def get_goal_telemetry(run_id: str, request: Request) -> GoalTelemetry:
    with _session(request) as session:
        try:
            return EvaluationTelemetryService(session).goal(run_id)
        except GoalTelemetryNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Goal telemetry not found.",
            ) from error


@router.get("/system", response_model=SystemTelemetry)
def get_system_telemetry(request: Request) -> SystemTelemetry:
    with _session(request) as session:
        return EvaluationTelemetryService(session).system()
