from __future__ import annotations

from datetime import UTC, datetime
from secrets import compare_digest
from typing import Annotated, cast

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks import (
    ApprovalResolveRequest,
    AsyncRunNotFound,
    AsyncRunStatus,
    AsyncTaskAccepted,
    AsyncTaskCreate,
    AsyncTaskPolicyGate,
    AsyncTaskRepository,
    AsyncTaskRun,
    AsyncTaskService,
    NotificationStatus,
)
from app.audit import AuditWriter
from app.capabilities.models import CapabilityKind
from app.capabilities.router import CapabilityRouter
from app.db.models import ApprovalRow
from app.routing.fast_router import FastRouter
from app.tasks import (
    TaskRepository,
    TaskService,
    TaskStatus,
)

router = APIRouter(
    prefix="/api/async-tasks",
    tags=["async-tasks"],
)


def require_internal_bearer(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    configured = request.app.state.settings.internal_api_token
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Internal API authentication is not configured."
            ),
        )

    scheme, separator, provided = (
        authorization or ""
    ).partition(" ")
    valid = (
        bool(separator)
        and scheme.casefold() == "bearer"
        and bool(provided)
        and compare_digest(provided, configured)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
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


def _policy(request: Request) -> AsyncTaskPolicyGate:
    return cast(
        AsyncTaskPolicyGate,
        request.app.state.async_policy_gate,
    )


def _audit(request: Request) -> AuditWriter:
    return cast(AuditWriter, request.app.state.audit_writer)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AsyncTaskAccepted,
    dependencies=[Depends(require_internal_bearer)],
)
def create_async_task(
    payload: AsyncTaskCreate,
    request: Request,
) -> AsyncTaskAccepted:
    if not bool(
        getattr(
            request.app.state,
            "accepting_async_tasks",
            False,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Async task runtime is not accepting new "
                "tasks."
            ),
        )

    if payload.governed_coding is None:
        fast_route_decision = FastRouter().route(payload.goal)
        capability_decision = CapabilityRouter().route(
            fast_route_decision,
            payload.goal,
        )
        if capability_decision.capability is CapabilityKind.CODE_OPERATION:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Code operation tasks require a governed_coding "
                    "assignment in an isolated worktree."
                ),
            )

    with _session(request) as session:
        service = AsyncTaskService(
            task_service=TaskService(
                TaskRepository(session),
                _audit(request),
            ),
            repository=AsyncTaskRepository(
                session,
                audit_writer=_audit(request),
            ),
            policy_gate=_policy(request),
        )
        accepted = service.create(payload)
        session.commit()
        return accepted


@router.post(
    "/approvals/{approval_id}/resolve",
    response_model=AsyncTaskRun,
    dependencies=[Depends(require_internal_bearer)],
)
def resolve_async_approval(
    approval_id: str,
    payload: ApprovalResolveRequest,
    request: Request,
) -> AsyncTaskRun:
    with _session(request) as session:
        service = AsyncTaskService(
            task_service=TaskService(TaskRepository(session), _audit(request)),
            repository=AsyncTaskRepository(session, audit_writer=_audit(request)),
            policy_gate=_policy(request),
        )
        try:
            service.resolve_approval(
                approval_id,
                resolved_by=payload.resolved_by,
                approved=payload.approved,
                action=payload.action,
            )
            session.commit()
            approval = session.get(ApprovalRow, approval_id)
            assert approval is not None
            return service.repository.get(approval.workflow_id)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

@router.get(
    "/{run_id}",
    response_model=AsyncTaskRun,
    dependencies=[Depends(require_internal_bearer)],
)
def get_async_task(
    run_id: str,
    request: Request,
) -> AsyncTaskRun:
    with _session(request) as session:
        try:
            return AsyncTaskRepository(session).get(run_id)
        except AsyncRunNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error


@router.get(
    "",
    response_model=list[AsyncTaskRun],
    dependencies=[Depends(require_internal_bearer)],
)
def list_async_tasks(
    request: Request,
    run_status: Annotated[
        AsyncRunStatus | None,
        Query(alias="status"),
    ] = None,
    task_id: Annotated[
        str | None,
        Query(min_length=1, max_length=64),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AsyncTaskRun]:
    with _session(request) as session:
        return AsyncTaskRepository(session).list_runs(
            status=run_status,
            task_id=task_id,
            limit=limit,
            offset=offset,
        )


@router.post(
    "/{run_id}/retry",
    response_model=AsyncTaskRun,
    dependencies=[Depends(require_internal_bearer)],
)
def retry_async_task(
    run_id: str,
    request: Request,
) -> AsyncTaskRun:
    now = datetime.now(UTC)
    with _session(request) as session:
        repository = AsyncTaskRepository(
            session,
            audit_writer=_audit(request),
        )
        try:
            run = repository.get(run_id)
        except AsyncRunNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

        payload = AsyncTaskCreate.model_validate_json(
            run.request_json
        )
        decision = _policy(request).evaluate(payload)
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=decision.message,
            )

        task_service = TaskService(
            TaskRepository(session),
            _audit(request),
        )
        try:
            retried = repository.manual_retry(
                run_id,
                now=now,
            )
            task_service.transition(
                run.task_id,
                TaskStatus.QUEUED,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        session.commit()
        return retried


@router.post(
    "/{run_id}/cancel",
    response_model=AsyncTaskRun,
    dependencies=[Depends(require_internal_bearer)],
)
def cancel_async_task(
    run_id: str,
    request: Request,
) -> AsyncTaskRun:
    now = datetime.now(UTC)
    with _session(request) as session:
        repository = AsyncTaskRepository(
            session,
            audit_writer=_audit(request),
        )
        repository.acquire_sqlite_write_lock()
        try:
            run = repository.get(run_id)
        except AsyncRunNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

        if run.status is AsyncRunStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Completed runs cannot be cancelled.",
            )

        try:
            cancelled = repository.cancel(
                run_id,
                now=now,
            )
            if run.status is not AsyncRunStatus.CANCELLED:
                TaskService(
                    TaskRepository(session),
                    _audit(request),
                ).cancel(
                    run.task_id,
                    reason="Cancelled through internal API.",
                )
            if cancelled.source_chat_id:
                repository.mark_notification(
                    run_id,
                    status=NotificationStatus.PENDING,
                    now=now,
                )
                cancelled = repository.get(run_id)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        session.commit()
        return cancelled
