from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Select, case, select, text, update
from sqlalchemy.orm import Session

from app.async_tasks.audit import write_async_run_event
from app.async_tasks.models import (
    ASYNC_RUN_TRANSITIONS,
    AsyncRunStatus,
    AsyncTaskCreate,
    AsyncTaskRun,
    NotificationStatus,
)
from app.audit import AuditWriter, SecretRedactor
from app.db.models import AsyncTaskRunRow, TaskRow
from app.privacy import (
    canonicalize_telegram_idempotency_key,
    legacy_telegram_idempotency_key,
    minimize_async_request_payload,
)


def new_async_run_id() -> str:
    return f"run_{uuid4().hex}"


class AsyncRunNotFound(RuntimeError):
    """Raised when an async run does not exist."""


class AsyncTaskRepository:
    def __init__(
        self,
        session: Session,
        *,
        audit_writer: AuditWriter | None = None,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self.session = session
        self.audit_writer = audit_writer
        self.redactor = redactor or SecretRedactor()

    def acquire_sqlite_write_lock(self) -> None:
        """Acquire an early write lock on a fresh SQLite session."""
        bind = self.session.get_bind()
        if bind.dialect.name != "sqlite":
            return
        if self.session.in_transaction():
            return
        self.session.execute(text("BEGIN IMMEDIATE"))

    def enqueue(
        self,
        *,
        task_id: str,
        request: AsyncTaskCreate,
        idempotency_key: str,
        now: datetime | None = None,
        status: AsyncRunStatus = AsyncRunStatus.PENDING,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AsyncTaskRun:
        provided_key = idempotency_key.strip()
        if not provided_key:
            raise ValueError("idempotency_key cannot be blank")
        normalized_key = provided_key
        lookup_keys = [provided_key]
        if request.source_channel == "telegram":
            normalized_key = canonicalize_telegram_idempotency_key(
                provided_key=provided_key,
                source_chat_id=request.source_chat_id,
                source_message_id=request.source_message_id,
            )
            lookup_keys.insert(0, normalized_key)
            if request.source_chat_id and request.source_message_id:
                lookup_keys.append(legacy_telegram_idempotency_key(
                    source_chat_id=request.source_chat_id,
                    source_message_id=request.source_message_id,
                ))

        for lookup_key in dict.fromkeys(lookup_keys):
            existing = self.get_by_idempotency_key(lookup_key)
            if existing is not None:
                return existing

        timestamp = self._utc(now)
        request_payload = minimize_async_request_payload(
            request.model_dump(mode="json")
        )
        request_payload["idempotency_key"] = normalized_key
        redacted_payload = self.redactor.redact(request_payload)

        row = AsyncTaskRunRow(
            id=new_async_run_id(),
            task_id=task_id,
            status=status.value,
            mode=request.mode.value,
            goal=str(self.redactor.redact(request.goal)),
            workspace=request.workspace,
            request_json=json.dumps(
                redacted_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            checkpoint_json=None,
            result_json=None,
            attempt=0,
            max_attempts=3,
            run_after=self._sqlite_time(timestamp),
            lease_owner=None,
            lease_expires_at=None,
            idempotency_key=normalized_key,
            external_run_id=None,
            last_error_code=(
                error_code[:128]
                if error_code is not None
                else None
            ),
            last_error_message=(
                str(self.redactor.redact(error_message))[:4000]
                if error_message is not None
                else None
            ),
            source_chat_id=request.source_chat_id,
            notification_status=(
                NotificationStatus.PENDING.value
                if (
                    request.source_chat_id
                    and status
                    in {
                        AsyncRunStatus.COMPLETED,
                        AsyncRunStatus.FAILED,
                        AsyncRunStatus.BLOCKED,
                        AsyncRunStatus.CANCELLED,
                    }
                )
                else NotificationStatus.NOT_REQUIRED.value
            ),
            notification_attempts=0,
            created_at=self._sqlite_time(timestamp),
            updated_at=self._sqlite_time(timestamp),
            version=1,
        )
        self.session.add(row)
        self.session.flush()
        run = self._to_model(row)
        write_async_run_event(
            self.audit_writer,
            "async_run.created",
            run,
            actor=request.requested_by,
            payload={"mode": run.mode.value},
        )
        if run.status is AsyncRunStatus.BLOCKED:
            write_async_run_event(
                self.audit_writer,
                "async_run.blocked",
                run,
                actor=request.requested_by,
                payload={"reason": error_code or "policy_gate"},
            )
        return run

    def get(self, run_id: str) -> AsyncTaskRun:
        row = self.session.get(AsyncTaskRunRow, run_id)
        if row is None:
            raise AsyncRunNotFound(
                f"Async run not found: {run_id}"
            )
        return self._to_model(row)

    def get_by_idempotency_key(
        self,
        key: str,
    ) -> AsyncTaskRun | None:
        statement = select(AsyncTaskRunRow).where(
            AsyncTaskRunRow.idempotency_key == key
        )
        row = self.session.execute(
            statement
        ).scalar_one_or_none()
        return None if row is None else self._to_model(row)

    def list_runs(
        self,
        *,
        status: AsyncRunStatus | None = None,
        task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AsyncTaskRun]:
        if not 1 <= limit <= 500:
            raise ValueError(
                "limit must be between 1 and 500"
            )
        if offset < 0:
            raise ValueError(
                "offset cannot be negative"
            )

        statement: Select[tuple[AsyncTaskRunRow]] = select(
            AsyncTaskRunRow
        ).order_by(
            AsyncTaskRunRow.created_at,
            AsyncTaskRunRow.id,
        )
        if status is not None:
            statement = statement.where(
                AsyncTaskRunRow.status == status.value
            )
        if task_id is not None:
            statement = statement.where(
                AsyncTaskRunRow.task_id == task_id
            )
        statement = statement.limit(limit).offset(offset)
        return [
            self._to_model(row)
            for row in self.session.execute(
                statement
            ).scalars()
        ]

    def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> AsyncTaskRun | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        timestamp = self._utc(now)
        sqlite_now = self._sqlite_time(timestamp)
        lease_expires = self._sqlite_time(
            timestamp + timedelta(seconds=lease_seconds)
        )

        critical_rank = case(
            (TaskRow.priority == "critical", 0),
            else_=1,
        )
        overdue_rank = case(
            (
                TaskRow.deadline.is_not(None)
                & (TaskRow.deadline <= sqlite_now),
                0,
            ),
            else_=1,
        )
        priority_rank = case(
            (TaskRow.priority == "high", 0),
            (TaskRow.priority == "normal", 1),
            (TaskRow.priority == "low", 2),
            else_=3,
        )
        deadline_rank = case(
            (TaskRow.deadline.is_(None), 1),
            else_=0,
        )

        candidate_id = (
            select(AsyncTaskRunRow.id)
            .join(TaskRow, TaskRow.id == AsyncTaskRunRow.task_id)
            .where(
                AsyncTaskRunRow.status.in_(
                    (
                        AsyncRunStatus.PENDING.value,
                        AsyncRunStatus.RETRY_WAIT.value,
                    )
                ),
                AsyncTaskRunRow.run_after <= sqlite_now,
                (
                    AsyncTaskRunRow.lease_expires_at.is_(None)
                    | (
                        AsyncTaskRunRow.lease_expires_at
                        < sqlite_now
                    )
                ),
            )
            .order_by(
                critical_rank,
                overdue_rank,
                priority_rank,
                deadline_rank,
                TaskRow.deadline,
                AsyncTaskRunRow.created_at,
                AsyncTaskRunRow.id,
            )
            .limit(1)
            .scalar_subquery()
        )

        statement = (
            update(AsyncTaskRunRow)
            .where(
                AsyncTaskRunRow.id == candidate_id,
                AsyncTaskRunRow.status.in_(
                    (
                        AsyncRunStatus.PENDING.value,
                        AsyncRunStatus.RETRY_WAIT.value,
                    )
                ),
            )
            .values(
                status=AsyncRunStatus.CLAIMED.value,
                lease_owner=worker_id,
                lease_expires_at=lease_expires,
                attempt=AsyncTaskRunRow.attempt + 1,
                version=AsyncTaskRunRow.version + 1,
                updated_at=sqlite_now,
            )
            .returning(AsyncTaskRunRow.id)
        )
        claimed_id = self.session.execute(
            statement
        ).scalar_one_or_none()
        if claimed_id is None:
            return None

        self.session.flush()
        run = self.get(claimed_id)
        write_async_run_event(
            self.audit_writer,
            "async_run.claimed",
            run,
            actor=worker_id,
            payload={
                "lease_expires_at": (
                    run.lease_expires_at.isoformat()
                    if run.lease_expires_at is not None
                    else None
                )
            },
        )
        return run

    def renew_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> AsyncTaskRun:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        row = self._require_row(run_id)
        if row.lease_owner != worker_id:
            raise ValueError("lease owner mismatch")

        timestamp = self._utc(now)
        row.lease_expires_at = self._sqlite_time(
            timestamp + timedelta(seconds=lease_seconds)
        )
        row.updated_at = self._sqlite_time(timestamp)
        row.version += 1
        self.session.flush()
        return self._to_model(row)

    def transition(
        self,
        run_id: str,
        target_status: AsyncRunStatus,
        *,
        now: datetime,
        checkpoint_json: str | None = None,
        result_json: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        external_run_id: str | None = None,
    ) -> AsyncTaskRun:
        row = self._require_row(run_id)
        current = AsyncRunStatus(row.status)
        if target_status not in ASYNC_RUN_TRANSITIONS[current]:
            raise ValueError(
                "Invalid async run transition: "
                f"{current.value} -> {target_status.value}"
            )

        timestamp = self._utc(now)
        row.status = target_status.value
        row.updated_at = self._sqlite_time(timestamp)
        row.version += 1

        if checkpoint_json is not None:
            row.checkpoint_json = str(
                self.redactor.redact(checkpoint_json)
            )
        if result_json is not None:
            row.result_json = str(
                self.redactor.redact(result_json)
            )
        if error_code is not None:
            row.last_error_code = error_code[:128]
        if error_message is not None:
            row.last_error_message = str(
                self.redactor.redact(error_message)
            )[:4000]
        if external_run_id is not None:
            row.external_run_id = external_run_id[:255]

        if target_status in {
            AsyncRunStatus.COMPLETED,
            AsyncRunStatus.FAILED,
            AsyncRunStatus.BLOCKED,
            AsyncRunStatus.CANCELLED,
        }:
            row.lease_owner = None
            row.lease_expires_at = None

        self.session.flush()
        run = self._to_model(row)
        terminal_event = {
            AsyncRunStatus.COMPLETED: "async_run.completed",
            AsyncRunStatus.FAILED: "async_run.failed",
            AsyncRunStatus.BLOCKED: "async_run.blocked",
            AsyncRunStatus.CANCELLED: "async_run.cancelled",
        }.get(target_status)
        if terminal_event is not None:
            write_async_run_event(
                self.audit_writer,
                terminal_event,
                run,
                payload={
                    "error_code": error_code,
                    "error_message": error_message,
                },
            )
        return run

    def schedule_retry(
        self,
        run_id: str,
        *,
        now: datetime,
        delay_seconds: int,
        error_code: str,
        error_message: str,
    ) -> AsyncTaskRun:
        row = self._require_row(run_id)
        current = AsyncRunStatus(row.status)
        if AsyncRunStatus.RETRY_WAIT not in ASYNC_RUN_TRANSITIONS[
            current
        ]:
            raise ValueError(
                "Current run status cannot schedule retry"
            )
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")

        timestamp = self._utc(now)
        row.status = AsyncRunStatus.RETRY_WAIT.value
        row.run_after = self._sqlite_time(
            timestamp + timedelta(seconds=delay_seconds)
        )
        row.lease_owner = None
        row.lease_expires_at = None
        row.last_error_code = error_code[:128]
        row.last_error_message = str(
            self.redactor.redact(error_message)
        )[:4000]
        row.updated_at = self._sqlite_time(timestamp)
        row.version += 1
        self.session.flush()
        run = self._to_model(row)
        write_async_run_event(
            self.audit_writer,
            "async_run.retry_scheduled",
            run,
            payload={
                "delay_seconds": delay_seconds,
                "error_code": error_code,
                "error_message": error_message,
                "run_after": run.run_after.isoformat(),
            },
        )
        return run

    def manual_retry(
        self,
        run_id: str,
        *,
        now: datetime,
    ) -> AsyncTaskRun:
        row = self._require_row(run_id)
        current = AsyncRunStatus(row.status)
        if current not in {
            AsyncRunStatus.FAILED,
            AsyncRunStatus.BLOCKED,
        }:
            raise ValueError(
                "Only failed or blocked runs may be retried"
            )

        timestamp = self._utc(now)
        row.status = AsyncRunStatus.PENDING.value
        row.attempt = 0
        row.run_after = self._sqlite_time(timestamp)
        row.lease_owner = None
        row.lease_expires_at = None
        row.checkpoint_json = None
        row.result_json = None
        row.external_run_id = None
        row.last_error_code = None
        row.last_error_message = None
        row.notification_status = (
            NotificationStatus.NOT_REQUIRED.value
        )
        row.notification_attempts = 0
        row.updated_at = self._sqlite_time(timestamp)
        row.version += 1
        self.session.flush()
        return self._to_model(row)

    def cancel(
        self,
        run_id: str,
        *,
        now: datetime,
    ) -> AsyncTaskRun:
        row = self._require_row(run_id)
        current = AsyncRunStatus(row.status)
        if current is AsyncRunStatus.CANCELLED:
            return self._to_model(row)
        if current not in {
            AsyncRunStatus.PENDING,
            AsyncRunStatus.RETRY_WAIT,
        }:
            raise ValueError(
                f"{current.value} runs cannot be cancelled safely"
            )

        timestamp = self._utc(now)
        statement = (
            update(AsyncTaskRunRow)
            .where(
                AsyncTaskRunRow.id == run_id,
                AsyncTaskRunRow.status.in_(
                    (
                        AsyncRunStatus.PENDING.value,
                        AsyncRunStatus.RETRY_WAIT.value,
                    )
                ),
            )
            .values(
                status=AsyncRunStatus.CANCELLED.value,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=self._sqlite_time(timestamp),
                version=AsyncTaskRunRow.version + 1,
            )
            .returning(AsyncTaskRunRow.id)
            .execution_options(synchronize_session=False)
        )
        updated_id = self.session.execute(
            statement
        ).scalar_one_or_none()
        if updated_id is None:
            self.session.expire(row)
            current_run = self.get(run_id)
            if current_run.status is AsyncRunStatus.CANCELLED:
                return current_run
            raise ValueError(
                f"{current_run.status.value} runs cannot be "
                "cancelled safely"
            )

        self.session.expire(row)
        run = self.get(run_id)
        write_async_run_event(
            self.audit_writer,
            "async_run.cancelled",
            run,
        )
        return run

    def recover_stale(
        self,
        run_id: str,
        *,
        safe_to_requeue: bool,
        now: datetime,
        reason: str,
    ) -> AsyncTaskRun:
        row = self._require_row(run_id)
        current = AsyncRunStatus(row.status)
        if current not in {
            AsyncRunStatus.CLAIMED,
            AsyncRunStatus.RUNNING,
            AsyncRunStatus.VERIFYING,
        }:
            raise ValueError(
                "Only active stale runs can be recovered"
            )

        timestamp = self._utc(now)
        row.status = (
            AsyncRunStatus.PENDING.value
            if safe_to_requeue
            else AsyncRunStatus.BLOCKED.value
        )
        row.run_after = self._sqlite_time(timestamp)
        row.lease_owner = None
        row.lease_expires_at = None
        row.last_error_code = (
            "stale_run_requeued"
            if safe_to_requeue
            else "stale_run_blocked"
        )
        row.last_error_message = str(
            self.redactor.redact(reason)
        )[:4000]
        row.updated_at = self._sqlite_time(timestamp)
        row.version += 1
        self.session.flush()
        run = self._to_model(row)
        write_async_run_event(
            self.audit_writer,
            "async_run.recovered",
            run,
            payload={
                "action": (
                    "requeued" if safe_to_requeue else "blocked"
                ),
                "reason": reason,
            },
        )
        if not safe_to_requeue:
            write_async_run_event(
                self.audit_writer,
                "async_run.blocked",
                run,
                payload={
                    "error_code": row.last_error_code,
                    "error_message": reason,
                    "recovery": True,
                },
            )
        return run

    def mark_notification(
        self,
        run_id: str,
        *,
        status: NotificationStatus,
        now: datetime,
        increment_attempts: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AsyncTaskRun:
        row = self._require_row(run_id)
        row.notification_status = status.value
        if increment_attempts:
            row.notification_attempts += 1
        row.updated_at = self._sqlite_time(self._utc(now))
        row.version += 1
        self.session.flush()
        run = self._to_model(row)
        if status is NotificationStatus.SENT:
            event_type = "async_notification.sent"
        elif (
            status is NotificationStatus.FAILED
            or error_code is not None
            or error_message is not None
        ):
            event_type = "async_notification.failed"
        else:
            event_type = None
        if event_type is not None:
            write_async_run_event(
                self.audit_writer,
                event_type,
                run,
                payload={
                    "notification_attempts": (
                        run.notification_attempts
                    ),
                    "error_code": error_code,
                    "error_message": error_message,
                    "retry_scheduled": (
                        status is NotificationStatus.PENDING
                    ),
                },
            )
        return run

    def claim_next_notification(
        self,
        *,
        now: datetime,
        max_attempts: int,
    ) -> AsyncTaskRun | None:
        if max_attempts <= 0:
            raise ValueError(
                "max_attempts must be positive"
            )

        timestamp = self._sqlite_time(self._utc(now))
        candidate_id = (
            select(AsyncTaskRunRow.id)
            .where(
                AsyncTaskRunRow.notification_status
                == NotificationStatus.PENDING.value,
                AsyncTaskRunRow.notification_attempts
                < max_attempts,
                AsyncTaskRunRow.source_chat_id.is_not(None),
                AsyncTaskRunRow.status.in_(
                    (
                        AsyncRunStatus.COMPLETED.value,
                        AsyncRunStatus.FAILED.value,
                        AsyncRunStatus.BLOCKED.value,
                        AsyncRunStatus.CANCELLED.value,
                    )
                ),
            )
            .order_by(
                AsyncTaskRunRow.updated_at,
                AsyncTaskRunRow.id,
            )
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(AsyncTaskRunRow)
            .where(
                AsyncTaskRunRow.id == candidate_id,
                AsyncTaskRunRow.notification_status
                == NotificationStatus.PENDING.value,
            )
            .values(
                notification_attempts=(
                    AsyncTaskRunRow.notification_attempts + 1
                ),
                updated_at=timestamp,
                version=AsyncTaskRunRow.version + 1,
            )
            .returning(AsyncTaskRunRow.id)
        )
        run_id = self.session.execute(
            statement
        ).scalar_one_or_none()
        if run_id is None:
            return None
        self.session.flush()
        return self.get(run_id)

    def list_stale_leases(
        self,
        *,
        now: datetime,
    ) -> list[AsyncTaskRun]:
        timestamp = self._sqlite_time(self._utc(now))
        statement: Select[tuple[AsyncTaskRunRow]] = (
            select(AsyncTaskRunRow)
            .where(
                AsyncTaskRunRow.status.in_(
                    (
                        AsyncRunStatus.CLAIMED.value,
                        AsyncRunStatus.RUNNING.value,
                        AsyncRunStatus.VERIFYING.value,
                    )
                ),
                AsyncTaskRunRow.lease_expires_at.is_not(None),
                AsyncTaskRunRow.lease_expires_at < timestamp,
            )
            .order_by(
                AsyncTaskRunRow.lease_expires_at,
                AsyncTaskRunRow.id,
            )
        )
        return [
            self._to_model(row)
            for row in self.session.execute(
                statement
            ).scalars()
        ]

    def list_legacy_approval_blocked_runs(
        self,
        *,
        limit: int = 500,
    ) -> list[AsyncTaskRun]:
        if not 1 <= limit <= 500:
            raise ValueError(
                "limit must be between 1 and 500"
            )
        statement: Select[tuple[AsyncTaskRunRow]] = (
            select(AsyncTaskRunRow)
            .where(
                AsyncTaskRunRow.status == AsyncRunStatus.BLOCKED.value,
                AsyncTaskRunRow.last_error_code == "approval_required",
            )
            .order_by(
                AsyncTaskRunRow.updated_at,
                AsyncTaskRunRow.id,
            )
            .limit(limit)
        )
        return [
            self._to_model(row)
            for row in self.session.execute(
                statement
            ).scalars()
        ]

    def _require_row(self, run_id: str) -> AsyncTaskRunRow:
        row = self.session.get(AsyncTaskRunRow, run_id)
        if row is None:
            raise AsyncRunNotFound(
                f"Async run not found: {run_id}"
            )
        return row

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _sqlite_time(value: datetime) -> datetime:
        return value.astimezone(UTC).replace(tzinfo=None)

    @staticmethod
    def _to_model(row: AsyncTaskRunRow) -> AsyncTaskRun:
        return AsyncTaskRun.model_validate(row)
