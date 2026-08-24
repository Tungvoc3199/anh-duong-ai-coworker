from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks.models import (
    AsyncTaskRun,
    NotificationStatus,
)
from app.async_tasks.repository import AsyncTaskRepository
from app.audit import AuditWriter
from app.openclaw.errors import OpenClawTransportError

MAX_NOTIFICATION_ATTEMPTS = 5


class FinalNotifier(Protocol):
    async def send_final(
        self,
        run: AsyncTaskRun,
    ) -> None: ...


class NotificationWorker:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        notifier: FinalNotifier,
        audit_writer: AuditWriter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.notifier = notifier
        self.audit_writer = audit_writer
        self.clock = clock or (lambda: datetime.now(UTC))

    async def run_once(self) -> bool:
        now = self._now()
        with self.session_factory() as session:
            repository = AsyncTaskRepository(
                session,
                audit_writer=self.audit_writer,
            )
            run = repository.claim_next_notification(
                now=now,
                max_attempts=MAX_NOTIFICATION_ATTEMPTS,
            )
            if run is None:
                session.rollback()
                return False
            session.commit()

        try:
            await self.notifier.send_final(run)
        except OpenClawTransportError as error:
            with self.session_factory() as session:
                repository = AsyncTaskRepository(
                session,
                audit_writer=self.audit_writer,
            )
                current = repository.get(run.id)
                retry = (
                    error.retryable
                    and current.notification_attempts
                    < MAX_NOTIFICATION_ATTEMPTS
                )
                repository.mark_notification(
                    run.id,
                    status=(
                        NotificationStatus.PENDING
                        if retry
                        else NotificationStatus.FAILED
                    ),
                    now=self._now(),
                    error_code=error.code,
                    error_message=str(error),
                )
                session.commit()
            return True

        with self.session_factory() as session:
            AsyncTaskRepository(
                session,
                audit_writer=self.audit_writer,
            ).mark_notification(
                run.id,
                status=NotificationStatus.SENT,
                now=self._now(),
            )
            session.commit()
        return True

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
