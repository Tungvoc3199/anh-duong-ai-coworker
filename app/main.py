from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.api.async_tasks import router as async_tasks_router
from app.api.health import router as health_router
from app.api.prepared_requests import router as prepared_requests_router
from app.async_tasks import (
    AsyncTaskExecutor,
    AsyncTaskPolicyGate,
    AsyncTaskWorker,
    FinalNotifier,
    NotificationWorker,
    recover_stale_runs,
)
from app.audit import AuditWriter
from app.cache.service import CacheService, CacheSettings
from app.config import Settings, get_settings
from app.context_builder import create_context_builder
from app.db.session import create_db_engine
from app.openclaw import OpenClawExecutor, OpenClawNotifier
from app.orchestration import create_core_request_pipeline

logger = logging.getLogger(__name__)


class RuntimeWorker(Protocol):
    async def run_once(self) -> bool: ...


@runtime_checkable
class AsyncCloseable(Protocol):
    async def aclose(self) -> None: ...


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    *,
    executor: AsyncTaskExecutor | None = None,
    notifier: FinalNotifier | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    policy_gate = AsyncTaskPolicyGate(
        tuple(runtime_settings.async_worker_workspace_roots)
    )
    audit_writer = AuditWriter(runtime_settings.audit_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_engine = app.state.engine is None
        if owns_engine:
            app.state.engine = create_db_engine(
                runtime_settings.database_url
            )

        stop_event: asyncio.Event | None = None
        runtime_executor: AsyncTaskExecutor | None = None
        runtime_notifier: FinalNotifier | None = None
        try:
            runtime_engine = app.state.engine
            if runtime_engine is None:
                raise RuntimeError(
                    "Database engine failed to initialize"
                )
            factory = sessionmaker(
                bind=runtime_engine,
                class_=Session,
                expire_on_commit=False,
                autoflush=False,
            )
            app.state.session_factory = factory
            if app.state.cache_service is not None:
                app.state.cache_service.start()
            app.state.background_tasks = []
            app.state.accepting_async_tasks = True
            app.state.async_runtime_ready = False

            if runtime_settings.async_worker_enabled:
                _validate_async_settings(runtime_settings)
                has_schema = inspect(runtime_engine).has_table(
                    "async_task_runs"
                )
                if has_schema:
                    needs_gateway_token = (
                        executor is None or notifier is None
                    )
                    if (
                        needs_gateway_token
                        and not runtime_settings.openclaw_auth_token
                    ):
                        raise RuntimeError(
                            "openclaw_auth_token is required "
                            "when async workers use OpenClaw."
                        )
                    recover_stale_runs(
                        factory,
                        audit_writer=audit_writer,
                        policy_gate=policy_gate,
                    )
                    runtime_executor = executor or OpenClawExecutor(
                        base_url=runtime_settings.openclaw_base_url,
                        execution_path=(
                            runtime_settings.openclaw_execution_path
                        ),
                        auth_token=(
                            runtime_settings.openclaw_auth_token
                        ),
                        timeout_seconds=(
                            runtime_settings.openclaw_timeout_seconds
                        ),
                    )
                    runtime_notifier = notifier or OpenClawNotifier(
                        base_url=runtime_settings.openclaw_base_url,
                        notification_path=(
                            runtime_settings.openclaw_notification_path
                        ),
                        auth_token=(
                            runtime_settings.openclaw_auth_token
                        ),
                        timeout_seconds=(
                            runtime_settings
                            .openclaw_notification_timeout_seconds
                        ),
                    )
                    execution_worker = AsyncTaskWorker(
                        session_factory=factory,
                        audit_writer=audit_writer,
                        policy_gate=policy_gate,
                        executor=runtime_executor,
                        worker_id=f"core-{uuid4().hex}",
                        lease_seconds=(
                            runtime_settings
                            .async_worker_lease_seconds
                        ),
                    )
                    notification_worker = NotificationWorker(
                        session_factory=factory,
                        notifier=runtime_notifier,
                        audit_writer=audit_writer,
                    )
                    stop_event = asyncio.Event()
                    app.state.background_tasks = [
                        asyncio.create_task(
                            _run_worker_loop(
                                execution_worker,
                                stop_event,
                                runtime_settings
                                .async_worker_poll_seconds,
                            ),
                            name="async-task-execution-worker",
                        ),
                        asyncio.create_task(
                            _run_worker_loop(
                                notification_worker,
                                stop_event,
                                runtime_settings
                                .async_worker_poll_seconds,
                            ),
                            name="async-task-notification-worker",
                        ),
                    ]
                    app.state.async_runtime_ready = True
            yield
        finally:
            app.state.accepting_async_tasks = False
            if stop_event is not None:
                stop_event.set()
            await _stop_background_tasks(
                app.state.background_tasks,
                runtime_settings.async_worker_shutdown_seconds,
            )
            await _close_component(runtime_executor)
            await _close_component(runtime_notifier)
            app.state.session_factory = None
            if owns_engine and app.state.engine is not None:
                app.state.engine.dispose()
                app.state.engine = None

    application = FastAPI(
        title=runtime_settings.app_name,
        version=runtime_settings.app_version,
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings
    application.state.engine = engine
    application.state.session_factory = None
    application.state.context_builder_factory = create_context_builder
    # Build cache settings from config
    cache_settings = CacheSettings(
        enabled=runtime_settings.cache_enabled,
        l1_enabled=runtime_settings.cache_l1_enabled,
        l2_enabled=runtime_settings.cache_l2_enabled,
        l1_max_entries=runtime_settings.cache_l1_max_entries_per_namespace,
        l1_max_bytes=runtime_settings.cache_l1_max_bytes_per_namespace,
        l2_max_payload_bytes=runtime_settings.cache_l2_max_payload_bytes,
        default_ttl_seconds=runtime_settings.cache_default_ttl_seconds,
        cache_db_path=runtime_settings.cache_db_path,
        persona_ttl_seconds=runtime_settings.cache_persona_ttl_seconds,
        memory_retrieval_ttl_seconds=runtime_settings.cache_memory_retrieval_ttl_seconds,
        l2_max_entries=runtime_settings.cache_l2_max_entries,
    )
    cache_service = (
        CacheService(cache_settings, runtime_settings.cache_db_path)
        if cache_settings.enabled
        else None
    )

    application.state.cache_service = cache_service
    application.state.core_request_pipeline_factory = partial(
        create_core_request_pipeline,
        audit_writer=audit_writer,
        persona_root=Path("data/persona"),
        cache_service=cache_service,
        persona_ttl_seconds=cache_settings.persona_ttl_seconds,
        memory_retrieval_ttl_seconds=cache_settings.memory_retrieval_ttl_seconds,
    )
    application.state.background_tasks = []
    application.state.accepting_async_tasks = False
    application.state.async_runtime_ready = False
    application.state.async_policy_gate = policy_gate
    application.state.audit_writer = audit_writer
    application.include_router(health_router)
    application.include_router(async_tasks_router)
    application.include_router(prepared_requests_router)
    return application


async def _run_worker_loop(
    worker: RuntimeWorker,
    stop_event: asyncio.Event,
    poll_seconds: float,
) -> None:
    while not stop_event.is_set():
        try:
            processed = await worker.run_once()
        except Exception:
            logger.exception("Async task background worker failed")
            processed = False
        if processed:
            continue
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=poll_seconds,
            )
        except TimeoutError:
            pass


async def _stop_background_tasks(
    tasks: list[asyncio.Task[None]],
    timeout_seconds: float,
) -> None:
    if not tasks:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(
                *tasks,
                return_exceptions=True,
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )


async def _close_component(
    component: object | None,
) -> None:
    if isinstance(component, AsyncCloseable):
        await component.aclose()


def _validate_async_settings(settings: Settings) -> None:
    if settings.async_worker_poll_seconds <= 0:
        raise RuntimeError(
            "async_worker_poll_seconds must be positive"
        )
    if settings.async_worker_lease_seconds <= 0:
        raise RuntimeError(
            "async_worker_lease_seconds must be positive"
        )
    if settings.async_worker_shutdown_seconds <= 0:
        raise RuntimeError(
            "async_worker_shutdown_seconds must be positive"
        )
    if not settings.async_worker_workspace_roots:
        raise RuntimeError(
            "async_worker_workspace_roots cannot be empty"
        )


app = create_app()
