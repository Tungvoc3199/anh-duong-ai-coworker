from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import CursorResult, and_, update
from sqlalchemy.orm import Session

from app.db.models import ApprovalRow


class ApprovalConflict(ValueError):
    """Approval is no longer valid for the requested identity/action."""


class ApprovalService:
    def __init__(
        self,
        session: Session,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def action_hash(action: str) -> str:
        return hashlib.sha256(action.encode("utf-8")).hexdigest()

    def create(
        self,
        *,
        workflow_id: str,
        task_id: str,
        action: str,
        risk_level: int,
        reason: str,
        preview: dict[str, Any] | None = None,
        scope: str = "single_action",
        ttl_seconds: int = 900,
    ) -> ApprovalRow:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = self._utc(self.clock())
        row = ApprovalRow(
            id=secrets.token_hex(16),
            workflow_id=workflow_id,
            task_id=task_id,
            action=action,
            action_hash=self.action_hash(action),
            risk_level=risk_level,
            scope=scope,
            reason=reason,
            preview=preview or {},
            status="pending",
            nonce=secrets.token_hex(16),
            expires_at=now + timedelta(seconds=ttl_seconds),
            requested_at=now,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def resolve(
        self,
        approval_id: str,
        *,
        workflow_id: str,
        task_id: str,
        action: str,
        resolved_by: str,
        approved: bool = True,
    ) -> ApprovalRow:
        now = self._utc(self.clock())
        expected_hash = self.action_hash(action)
        status = "approved" if approved else "denied"
        statement = (
            update(ApprovalRow)
            .execution_options(synchronize_session=False)
            .where(
                and_(
                    ApprovalRow.id == approval_id,
                    ApprovalRow.workflow_id == workflow_id,
                    ApprovalRow.task_id == task_id,
                    ApprovalRow.action_hash == expected_hash,
                    ApprovalRow.status == "pending",
                    ApprovalRow.expires_at > now,
                )
            )
            .values(status=status, resolved_at=now, resolved_by=resolved_by)
        )
        result = self.session.execute(statement)
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise ApprovalConflict("Approval identity, action, status, or expiry mismatch")
        self.session.flush()
        self.session.expire_all()
        row = self.session.get(ApprovalRow, approval_id)
        assert row is not None
        return row

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
