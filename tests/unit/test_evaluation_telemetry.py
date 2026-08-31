from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import ApprovalRow, AsyncTaskRunRow, TaskRow, WorkflowRow
from app.db.session import create_db_engine

NOW = datetime(2026, 8, 31, 5, 0, tzinfo=UTC)
SECRET = "sk-secret-must-never-appear"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    runtime_engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path / 'telemetry.db'}")
    Base.metadata.create_all(runtime_engine)
    try:
        yield runtime_engine
    finally:
        runtime_engine.dispose()


def _plan(
    *,
    revision: int = 1,
    retries_used: int = 0,
    capabilities: tuple[str, ...] = ("system_operation",),
    dod: bool = True,
    replan_reason: str | None = None,
) -> dict[str, Any]:
    criteria = (
        [
            {
                "criterion": f"do not leak {SECRET}",
                "satisfied": True,
                "status": "verified",
                "reason": "verified by secret-bearing evidence",
            }
        ]
        if dod
        else []
    )
    return {
        "revision": revision,
        "replanned_from_revision": revision - 1 if revision > 1 else None,
        "replan_reason": replan_reason,
        "nodes": [
            {
                "id": "execute",
                "title": "execute secret task",
                "kind": "action",
                "depends_on": [],
                "capability_requirements": list(capabilities),
                "verification_requirements": [],
            }
        ],
        "node_executions": [
            {
                "node_id": "execute",
                "state": "completed",
                "attempts": revision,
                "evidence_ids": ["secret-evidence-id"],
                "last_failure_class": None,
            }
        ],
        "execution_budget": {
            "max_actions": 12,
            "max_elapsed_seconds": 1800,
            "actions_used": revision,
            "retries_used": retries_used,
            "started_at": NOW.isoformat(),
        },
        "outcome_judgement": {
            "disposition": "satisfied" if dod else "blocked",
            "criteria": criteria,
            "reason_code": "dod_satisfied" if dod else "approval_required",
            "reason": f"secret reason {SECRET}",
        },
        "evidence": [
            {
                "id": "ev:execute:r1:a1",
                "node_id": "execute",
                "kind": "result",
                "summary": f"secret evidence {SECRET}",
                "artifact_refs": [],
                "verification_refs": [],
                "outcome": "completed",
                "criterion_verification": [],
                "provenance": "openclaw",
            }
        ],
    }


def _seed_goal(
    session: Session,
    *,
    suffix: str,
    status: str,
    elapsed_seconds: int = 10,
    attempt: int = 1,
    notification_status: str = "sent",
    notification_attempts: int = 1,
    last_error_code: str | None = None,
    plan: object | None = None,
    approval_status: str | None = None,
    approval_resolved: bool = False,
) -> str:
    task_id = f"task_{suffix}"
    run_id = f"run_{suffix}"
    created = NOW + timedelta(minutes=len(session.new))
    updated = created + timedelta(seconds=elapsed_seconds)
    session.add(
        TaskRow(
            id=task_id,
            title=f"secret title {SECRET}",
            description=f"secret prompt {SECRET}",
            status=status,
            priority="normal",
            risk_level=0,
            requested_by="user",
            source_channel="telegram",
            approval_required=approval_status is not None,
            result_summary=f"secret task result {SECRET}",
            created_at=created,
            updated_at=updated,
        )
    )
    session.flush()
    session.add(
        AsyncTaskRunRow(
            id=run_id,
            task_id=task_id,
            status=status,
            mode="quick",
            goal=f"secret goal {SECRET}",
            workspace=None,
            request_json=json.dumps({"goal": SECRET, "token": SECRET}),
            checkpoint_json=json.dumps({"message": SECRET}),
            result_json=json.dumps({"summary": SECRET, "outcome": status}),
            attempt=attempt,
            max_attempts=3,
            run_after=created,
            idempotency_key=f"idem:{suffix}",
            external_run_id=f"resp_{suffix}",
            last_error_code=last_error_code,
            last_error_message=f"secret error {SECRET}" if last_error_code else None,
            source_chat_id="123456",
            notification_status=notification_status,
            notification_attempts=notification_attempts,
            created_at=created,
            updated_at=updated,
        )
    )
    if plan is not None:
        session.add(
            WorkflowRow(
                id=run_id,
                task_id=task_id,
                status="pending",
                context_payload={"raw_prompt": SECRET},
                plan_payload=plan,  # type: ignore[arg-type]
                result_summary=f"secret workflow result {SECRET}",
                created_at=created,
                updated_at=updated,
            )
        )
    session.flush()
    if approval_status is not None:
        session.add(
            ApprovalRow(
                id=f"approval_{suffix}",
                workflow_id=run_id,
                task_id=task_id,
                action=f"secret action {SECRET}",
                action_hash="a" * 64,
                risk_level=1,
                scope="single_action",
                reason=f"secret approval reason {SECRET}",
                preview={"secret": SECRET},
                status=approval_status,
                nonce=f"nonce_{suffix}",
                expires_at=created + timedelta(hours=1),
                requested_at=created,
                resolved_at=(created + timedelta(seconds=2)) if approval_resolved else None,
                resolved_by="owner" if approval_resolved else None,
                created_at=created,
                updated_at=updated,
            )
        )
    session.commit()
    return run_id


def _service(session: Session):
    import app.evaluation as evaluation

    assert hasattr(evaluation, "EvaluationTelemetryService"), (
        "EvaluationTelemetryService must be exported by app.evaluation"
    )
    return evaluation.EvaluationTelemetryService(session)


def test_successful_autonomous_goal_projects_trustworthy_metrics(engine: Engine) -> None:
    with Session(engine) as session:
        run_id = _seed_goal(session, suffix="ok", status="completed", plan=_plan())
        goal = _service(session).goal(run_id)

    assert goal.status == "completed"
    assert goal.metrics["outcome"].value == "success"
    assert goal.metrics["human_intervention_count"].value == 0
    assert goal.metrics["approvals"].value == {
        "total": 0,
        "pending": 0,
        "approved": 0,
        "denied": 0,
    }
    assert goal.metrics["elapsed_seconds"].value == 10.0
    assert goal.metrics["retries"].value == 0
    assert goal.metrics["replans"].value == 0
    assert goal.metrics["route"].value == "workflow"
    assert goal.metrics["capabilities"].value == ["system_operation"]
    assert goal.metrics["dod_verification_quality"].value == {
        "score": 1.0,
        "verified": 1,
        "total": 1,
        "disposition": "satisfied",
    }


def test_blocked_failed_and_approval_required_goals_remain_distinct(engine: Engine) -> None:
    with Session(engine) as session:
        blocked = _seed_goal(
            session,
            suffix="blocked",
            status="blocked",
            plan=_plan(dod=False),
            approval_status="pending",
        )
        failed = _seed_goal(
            session,
            suffix="failed",
            status="failed",
            plan=_plan(dod=False),
            last_error_code="provider_error",
        )
        service = _service(session)
        blocked_goal = service.goal(blocked)
        failed_goal = service.goal(failed)

    assert blocked_goal.metrics["outcome"].value == "blocked"
    assert blocked_goal.metrics["approvals"].value["pending"] == 1
    assert blocked_goal.metrics["human_intervention_count"].value == 0
    assert failed_goal.metrics["outcome"].value == "failed"
    assert failed_goal.metrics["failure_classes"].value == ["provider_error"]


def test_resolved_approval_is_human_intervention(engine: Engine) -> None:
    with Session(engine) as session:
        run_id = _seed_goal(
            session,
            suffix="human",
            status="blocked",
            plan=_plan(dod=False),
            approval_status="denied",
            approval_resolved=True,
        )
        goal = _service(session).goal(run_id)

    assert goal.metrics["human_intervention_count"].value == 1
    assert goal.metrics["approvals"].value["denied"] == 1


def test_replan_and_notification_retry_are_recovery_evidence(engine: Engine) -> None:
    with Session(engine) as session:
        run_id = _seed_goal(
            session,
            suffix="recovered",
            status="completed",
            attempt=2,
            notification_status="sent",
            notification_attempts=2,
            plan=_plan(
                revision=2,
                retries_used=1,
                capabilities=("planning", "system_operation"),
                replan_reason=(
                    "Evidence-driven replan after dod_unmet_recoverable: "
                    "definition of done was unmet"
                ),
            ),
        )
        goal = _service(session).goal(run_id)

    assert goal.metrics["retries"].value == 1
    assert goal.metrics["replans"].value == 1
    assert goal.metrics["failure_classes"].value == ["dod_unmet_recoverable"]
    assert goal.metrics["recovery"].value == {
        "opportunity": True,
        "autonomous_recovered": True,
    }
    assert goal.metrics["delivery"].value == {
        "notification_status": "sent",
        "notification_attempts": 2,
        "delivery_recovered": True,
    }


def test_notification_failure_is_visible(engine: Engine) -> None:
    with Session(engine) as session:
        run_id = _seed_goal(
            session,
            suffix="notifyfail",
            status="failed",
            notification_status="failed",
            notification_attempts=3,
            plan=_plan(dod=False),
        )
        goal = _service(session).goal(run_id)

    assert goal.metrics["delivery"].value == {
        "notification_status": "failed",
        "notification_attempts": 3,
        "delivery_recovered": False,
    }


def test_missing_or_malformed_telemetry_is_unsupported_not_zero(engine: Engine) -> None:
    with Session(engine) as session:
        missing = _seed_goal(session, suffix="missing", status="completed", plan=None)
        malformed = _seed_goal(
            session,
            suffix="malformed",
            status="completed",
            plan="not-a-plan-object",
        )
        service = _service(session)
        missing_goal = service.goal(missing)
        malformed_goal = service.goal(malformed)

    for goal in (missing_goal, malformed_goal):
        for metric_name in (
            "dod_verification_quality",
            "replans",
            "route",
            "capabilities",
            "token_usage",
            "context_usage",
            "output_usage",
            "cost",
            "cache_attribution",
            "regression_indicator",
        ):
            metric = goal.metrics[metric_name]
            assert metric.support == "unsupported"
            assert metric.value is None
            assert metric.reason


def test_projection_never_leaks_prompt_result_or_secret_text(engine: Engine) -> None:
    with Session(engine) as session:
        run_id = _seed_goal(
            session,
            suffix="secret",
            status="completed",
            plan=_plan(
                revision=2,
                replan_reason=(
                    "Evidence-driven replan after dod_unmet_recoverable: " + SECRET
                ),
            ),
        )
        goal = _service(session).goal(run_id)
        serialized = goal.model_dump_json()

    assert SECRET not in serialized
    for forbidden in ("goal", "prompt", "summary", "request_json", "result_json"):
        assert f'"{forbidden}"' not in serialized


def test_system_aggregation_is_idempotent_restart_safe_and_reproducible(engine: Engine) -> None:
    with Session(engine) as session:
        _seed_goal(
            session,
            suffix="sys_ok",
            status="completed",
            elapsed_seconds=10,
            plan=_plan(capabilities=("system_operation",)),
        )
        _seed_goal(
            session,
            suffix="sys_recovered",
            status="completed",
            elapsed_seconds=30,
            attempt=2,
            plan=_plan(
                revision=2,
                capabilities=("planning", "system_operation"),
                replan_reason=(
                    "Evidence-driven replan after dod_unmet_recoverable: unmet"
                ),
            ),
        )
        _seed_goal(
            session,
            suffix="sys_human",
            status="blocked",
            elapsed_seconds=20,
            plan=_plan(dod=False, capabilities=("planning",)),
            approval_status="approved",
            approval_resolved=True,
        )
        first = _service(session).system()
        second = _service(session).system()

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.population == {
        "terminal_goals": 3,
        "completed": 2,
        "blocked": 1,
        "failed": 0,
    }
    assert first.metrics["autonomous_completion_rate"].value == pytest.approx(2 / 3)
    assert first.metrics["human_intervention_rate"].value == pytest.approx(1 / 3)
    assert first.metrics["autonomous_recovery_rate"].value == 1.0
    assert first.metrics["p95_completion_seconds"].value == 30.0
    assert first.metrics["capability_utilization"].value == {
        "counts": {"planning": 2, "system_operation": 2},
        "observed_goals": 3,
        "terminal_goals": 3,
        "coverage_rate": 1.0,
    }
    for metric_name in (
        "token_per_successful_goal",
        "cost_per_successful_goal",
        "skill_utilization",
        "quality_regression_rate",
    ):
        metric = first.metrics[metric_name]
        assert metric.support == "unsupported"
        assert metric.value is None
        assert metric.reason


def test_recovery_rate_is_unsupported_when_no_recovery_opportunity(engine: Engine) -> None:
    with Session(engine) as session:
        _seed_goal(session, suffix="only", status="completed", plan=_plan())
        system = _service(session).system()

    metric = system.metrics["autonomous_recovery_rate"]
    assert metric.support == "unsupported"
    assert metric.value is None
    assert "opportunity" in metric.reason.lower()


def test_capability_utilization_reports_partial_coverage(engine: Engine) -> None:
    with Session(engine) as session:
        _seed_goal(
            session,
            suffix="cap_observed",
            status="completed",
            plan=_plan(capabilities=("planning",)),
        )
        _seed_goal(
            session,
            suffix="cap_missing",
            status="failed",
            plan=None,
        )
        system = _service(session).system()

    assert system.metrics["capability_utilization"].value == {
        "counts": {"planning": 1},
        "observed_goals": 1,
        "terminal_goals": 2,
        "coverage_rate": 0.5,
    }
