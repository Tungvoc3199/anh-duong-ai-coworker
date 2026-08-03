from __future__ import annotations

from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from app.api.async_tasks import require_internal_bearer
from app.orchestration import (
    CoreRequest,
    CoreRequestPipeline,
    PreparedRequest,
    ProjectContextNotFound,
    ProjectResolutionFailed,
    TaskContextNotFound,
    TaskProjectMismatch,
    WorkflowPreparationFailed,
)

router = APIRouter(
    prefix="/api/internal/requests",
    tags=["internal-requests"],
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


def _pipeline(request: Request, session: Session) -> CoreRequestPipeline:
    factory = cast(
        Callable[[Session], CoreRequestPipeline],
        request.app.state.core_request_pipeline_factory,
    )
    return factory(session)


@router.post(
    "/prepare",
    response_model=PreparedRequest,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_internal_bearer)],
)
def prepare_request(
    payload: CoreRequest,
    request: Request,
) -> PreparedRequest:
    with _session(request) as session:
        try:
            return _pipeline(request, session).prepare(payload)
        except (ProjectContextNotFound, TaskContextNotFound) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except TaskProjectMismatch as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        except ProjectResolutionFailed as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        except WorkflowPreparationFailed as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error
