from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApprovalRow, AsyncTaskRunRow, TaskRow, WorkflowRow
from app.evaluation.models import GoalTelemetry, MetricDatum, MetricSupport, SystemTelemetry

_TERMINAL = frozenset({"completed", "blocked", "failed"})
_REPLAN_CLASS = re.compile(r"\bafter\s+([a-z0-9_]+)\s*:", re.IGNORECASE)


class GoalTelemetryNotFound(LookupError):
    pass


def _available(value: Any, *, producer: str, source: str) -> MetricDatum:
    return MetricDatum(
        support=MetricSupport.AVAILABLE,
        value=value,
        producer=producer,
        durable_source=source,
    )


def _derived(value: Any, *, producer: str, source: str) -> MetricDatum:
    return MetricDatum(
        support=MetricSupport.DERIVED,
        value=value,
        producer=producer,
        durable_source=source,
    )


def _unsupported(*, producer: str, source: str, reason: str) -> MetricDatum:
    return MetricDatum(
        support=MetricSupport.UNSUPPORTED,
        value=None,
        producer=producer,
        durable_source=source,
        reason=reason,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _plan_dict(workflow: WorkflowRow | None) -> dict[str, Any] | None:
    payload = workflow.plan_payload if workflow is not None else None
    return payload if isinstance(payload, dict) and payload else None


class EvaluationTelemetryService:
    """Read-only projections over durable goal state; never persists aggregates."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def goal(self, run_id: str) -> GoalTelemetry:
        run = self.session.get(AsyncTaskRunRow, run_id)
        if run is None:
            raise GoalTelemetryNotFound(run_id)
        task = self.session.get(TaskRow, run.task_id)
        if task is None:
            raise GoalTelemetryNotFound(run_id)
        workflow = self.session.get(WorkflowRow, run_id)
        if workflow is None:
            workflow = self.session.scalar(
                select(WorkflowRow)
                .where(WorkflowRow.task_id == run.task_id)
                .order_by(WorkflowRow.created_at.desc())
            )
        approvals = list(
            self.session.scalars(
                select(ApprovalRow).where(ApprovalRow.task_id == run.task_id)
            )
        )
        plan = _plan_dict(workflow)
        metrics = self._goal_metrics(run, task, approvals, plan)
        return GoalTelemetry(
            run_id=run.id,
            task_id=run.task_id,
            status=run.status,
            metrics=metrics,
        )

    def system(self) -> SystemTelemetry:
        run_ids = list(
            self.session.scalars(
                select(AsyncTaskRunRow.id)
                .where(AsyncTaskRunRow.status.in_(tuple(_TERMINAL)))
                .order_by(AsyncTaskRunRow.created_at.asc(), AsyncTaskRunRow.id.asc())
            )
        )
        goals = [self.goal(run_id) for run_id in run_ids]
        completed = [goal for goal in goals if goal.status == "completed"]
        blocked = [goal for goal in goals if goal.status == "blocked"]
        failed = [goal for goal in goals if goal.status == "failed"]
        population = {
            "terminal_goals": len(goals),
            "completed": len(completed),
            "blocked": len(blocked),
            "failed": len(failed),
        }
        metrics: dict[str, MetricDatum] = {}
        if goals:
            autonomous_completed = sum(
                goal.status == "completed"
                and goal.metrics["human_intervention_count"].value == 0
                for goal in goals
            )
            metrics["autonomous_completion_rate"] = _derived(
                autonomous_completed / len(goals),
                producer="evaluation_projection",
                source="tasks.status+approvals.resolved_at",
            )
            intervened = sum(
                int(goal.metrics["human_intervention_count"].value or 0) > 0
                for goal in goals
            )
            metrics["human_intervention_rate"] = _derived(
                intervened / len(goals),
                producer="evaluation_projection",
                source="approvals.resolved_at",
            )
        else:
            metrics["autonomous_completion_rate"] = _unsupported(
                producer="evaluation_projection",
                source="async_task_runs.status",
                reason="No terminal goals exist in the durable population.",
            )
            metrics["human_intervention_rate"] = _unsupported(
                producer="evaluation_projection",
                source="approvals.resolved_at",
                reason="No terminal goals exist in the durable population.",
            )

        observed_recovery_goals = [
            goal
            for goal in goals
            if goal.metrics["recovery"].support is not MetricSupport.UNSUPPORTED
        ]
        recovery_goals = [
            goal
            for goal in observed_recovery_goals
            if bool((goal.metrics["recovery"].value or {}).get("opportunity"))
        ]
        if recovery_goals:
            recovered = sum(
                bool((goal.metrics["recovery"].value or {}).get("autonomous_recovered"))
                for goal in recovery_goals
            )
            metrics["autonomous_recovery_rate"] = _derived(
                {
                    "rate": recovered / len(recovery_goals),
                    "autonomous_recovered": recovered,
                    "recovery_opportunities": len(recovery_goals),
                    "observed_goals": len(observed_recovery_goals),
                    "terminal_goals": len(goals),
                    "coverage_rate": len(observed_recovery_goals) / len(goals),
                },
                producer="evaluation_projection",
                source="workflows.plan_payload+async_task_runs.attempt+approvals.resolved_at",
            )
        else:
            metrics["autonomous_recovery_rate"] = _unsupported(
                producer="evaluation_projection",
                source="workflows.plan_payload+async_task_runs.attempt",
                reason="No durable retry or replan recovery opportunity exists.",
            )

        elapsed = sorted(
            float(goal.metrics["elapsed_seconds"].value)
            for goal in completed
            if goal.metrics["elapsed_seconds"].support is not MetricSupport.UNSUPPORTED
        )
        if elapsed:
            index = max(0, math.ceil(0.95 * len(elapsed)) - 1)
            metrics["p95_completion_seconds"] = _derived(
                elapsed[index],
                producer="evaluation_projection",
                source="tasks.created_at+tasks.updated_at",
            )
        else:
            metrics["p95_completion_seconds"] = _unsupported(
                producer="evaluation_projection",
                source="tasks.created_at+tasks.updated_at",
                reason="No completed goal has durable lifecycle timestamps.",
            )

        capability_counts: dict[str, int] = {}
        observed_capability_goals = 0
        for goal in goals:
            datum = goal.metrics["capabilities"]
            if datum.support is MetricSupport.UNSUPPORTED:
                continue
            observed_capability_goals += 1
            for capability in datum.value or []:
                capability_counts[str(capability)] = capability_counts.get(str(capability), 0) + 1
        if observed_capability_goals:
            metrics["capability_utilization"] = _derived(
                {
                    "counts": dict(sorted(capability_counts.items())),
                    "observed_goals": observed_capability_goals,
                    "terminal_goals": len(goals),
                    "coverage_rate": observed_capability_goals / len(goals),
                },
                producer="evaluation_projection",
                source="workflows.plan_payload.nodes.capability_requirements",
            )
        else:
            metrics["capability_utilization"] = _unsupported(
                producer="evaluation_projection",
                source="workflows.plan_payload.nodes.capability_requirements",
                reason="No terminal goal has durable capability attribution.",
            )

        metrics["token_per_successful_goal"] = _unsupported(
            producer="missing_run_usage_producer",
            source="none",
            reason="Actual run-scoped token usage is not durably produced.",
        )
        metrics["cost_per_successful_goal"] = _unsupported(
            producer="missing_run_cost_producer",
            source="none",
            reason="Monetary run cost is not durably produced.",
        )
        metrics["skill_utilization"] = _unsupported(
            producer="missing_skill_execution_producer",
            source="skill_executions",
            reason="Skill execution rows are not produced for current async goals.",
        )
        metrics["quality_regression_rate"] = _unsupported(
            producer="missing_regression_baseline_producer",
            source="none",
            reason="No durable quality baseline/cohort comparison exists.",
        )
        return SystemTelemetry(population=population, metrics=metrics)

    def _goal_metrics(
        self,
        run: AsyncTaskRunRow,
        task: TaskRow,
        approvals: list[ApprovalRow],
        plan: dict[str, Any] | None,
    ) -> dict[str, MetricDatum]:
        outcome = {
            "completed": "success",
            "blocked": "blocked",
            "failed": "failed",
        }.get(run.status, run.status)
        metrics: dict[str, MetricDatum] = {
            "outcome": _available(
                outcome,
                producer="async_task_worker",
                source="async_task_runs.status",
            )
        }
        resolved = sum(approval.resolved_at is not None for approval in approvals)
        metrics["human_intervention_count"] = _derived(
            resolved,
            producer="evaluation_projection",
            source="approvals.resolved_at",
        )
        approval_states = {
            "total": len(approvals),
            "pending": sum(approval.status == "pending" for approval in approvals),
            "approved": sum(approval.status == "approved" for approval in approvals),
            "denied": sum(approval.status == "denied" for approval in approvals),
        }
        metrics["approvals"] = _derived(
            approval_states,
            producer="evaluation_projection",
            source="approvals.status",
        )
        if run.status in _TERMINAL and task.created_at is not None and task.updated_at is not None:
            seconds = max(
                0.0,
                (_as_utc(task.updated_at) - _as_utc(task.created_at)).total_seconds(),
            )
            metrics["elapsed_seconds"] = _derived(
                seconds,
                producer="evaluation_projection",
                source="tasks.created_at+tasks.updated_at",
            )
        else:
            metrics["elapsed_seconds"] = _unsupported(
                producer="evaluation_projection",
                source="tasks.created_at+tasks.updated_at",
                reason="Goal is non-terminal or lifecycle timestamps are unavailable.",
            )

        retries_used: int | None = None
        if plan is not None:
            budget = plan.get("execution_budget")
            if isinstance(budget, dict) and isinstance(budget.get("retries_used"), int):
                retries_used = max(int(budget["retries_used"]), 0)
        if retries_used is None:
            retries_used = max(int(run.attempt) - 1, 0)
            retry_source = "async_task_runs.attempt"
        else:
            retry_source = "workflows.plan_payload.execution_budget.retries_used"
        metrics["retries"] = _derived(
            retries_used,
            producer="evaluation_projection",
            source=retry_source,
        )

        replan_count: int | None = None
        if plan is not None and isinstance(plan.get("revision"), int):
            revision = int(plan["revision"])
            if revision >= 1:
                replan_count = revision - 1
        if replan_count is None:
            metrics["replans"] = _unsupported(
                producer="evaluation_projection",
                source="workflows.plan_payload.revision",
                reason="A valid durable plan revision is unavailable.",
            )
        else:
            metrics["replans"] = _derived(
                replan_count,
                producer="evaluation_projection",
                source="workflows.plan_payload.revision",
            )

        failure_classes: set[str] = set()
        if run.last_error_code:
            failure_classes.add(run.last_error_code)
        if plan is not None:
            executions = plan.get("node_executions")
            if isinstance(executions, list):
                for item in executions:
                    if isinstance(item, dict) and isinstance(item.get("last_failure_class"), str):
                        value = item["last_failure_class"].strip()
                        if value:
                            failure_classes.add(value)
            replan_reason = plan.get("replan_reason")
            if isinstance(replan_reason, str):
                match = _REPLAN_CLASS.search(replan_reason)
                if match:
                    failure_classes.add(match.group(1).casefold())
        metrics["failure_classes"] = _derived(
            sorted(failure_classes),
            producer="evaluation_projection",
            source="async_task_runs.last_error_code+workflows.plan_payload",
        )

        if plan is None:
            metrics["route"] = _unsupported(
                producer="evaluation_projection",
                source="workflows.plan_payload",
                reason="No valid durable workflow plan exists for route attribution.",
            )
            metrics["capabilities"] = _unsupported(
                producer="evaluation_projection",
                source="workflows.plan_payload.nodes.capability_requirements",
                reason="No valid durable workflow plan exists for capability attribution.",
            )
            metrics["dod_verification_quality"] = _unsupported(
                producer="core_outcome_judge",
                source="workflows.plan_payload.outcome_judgement.criteria",
                reason="Final Outcome Judge criteria are unavailable.",
            )
        else:
            metrics["route"] = _derived(
                "workflow",
                producer="evaluation_projection",
                source="workflows.plan_payload",
            )
            capabilities: set[str] = set()
            nodes = plan.get("nodes")
            if isinstance(nodes, list):
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    values = node.get("capability_requirements")
                    if isinstance(values, list):
                        capabilities.update(
                            item for item in values if isinstance(item, str) and item.strip()
                        )
            metrics["capabilities"] = _derived(
                sorted(capabilities),
                producer="goal_planner",
                source="workflows.plan_payload.nodes.capability_requirements",
            )
            judgement = plan.get("outcome_judgement")
            criteria = judgement.get("criteria") if isinstance(judgement, dict) else None
            if isinstance(criteria, list) and criteria:
                total = len(criteria)
                verified = sum(
                    isinstance(item, dict)
                    and item.get("satisfied") is True
                    and item.get("status") == "verified"
                    for item in criteria
                )
                metrics["dod_verification_quality"] = _derived(
                    {
                        "score": verified / total,
                        "verified": verified,
                        "total": total,
                        "disposition": judgement.get("disposition"),
                    },
                    producer="core_outcome_judge",
                    source="workflows.plan_payload.outcome_judgement.criteria",
                )
            else:
                metrics["dod_verification_quality"] = _unsupported(
                    producer="core_outcome_judge",
                    source="workflows.plan_payload.outcome_judgement.criteria",
                    reason="Final Outcome Judge criteria are unavailable.",
                )

        replan_known = metrics["replans"].support is not MetricSupport.UNSUPPORTED
        if retries_used > 0 or replan_known:
            opportunity = retries_used > 0 or int(metrics["replans"].value or 0) > 0
            metrics["recovery"] = _derived(
                {
                    "opportunity": opportunity,
                    "autonomous_recovered": (
                        opportunity and run.status == "completed" and resolved == 0
                    ),
                },
                producer="evaluation_projection",
                source="workflows.plan_payload+async_task_runs.attempt+approvals.resolved_at",
            )
        else:
            metrics["recovery"] = _unsupported(
                producer="evaluation_projection",
                source="workflows.plan_payload+async_task_runs.attempt",
                reason="No retry occurred and replan history is unavailable.",
            )
        metrics["delivery"] = _derived(
            {
                "notification_status": run.notification_status,
                "notification_attempts": run.notification_attempts,
                "delivery_recovered": (
                    run.notification_status == "sent" and run.notification_attempts > 1
                ),
            },
            producer="notification_worker",
            source="async_task_runs.notification_status+notification_attempts",
        )

        for name, producer, reason in (
            (
                "token_usage",
                "missing_run_usage_producer",
                "Actual input/output token usage is not durably attributed to this run.",
            ),
            (
                "context_usage",
                "missing_run_context_usage_producer",
                "Context Builder estimates are not durably attributed to this async run.",
            ),
            (
                "output_usage",
                "missing_run_output_usage_producer",
                "Actual output token/byte usage is not durably produced for this run.",
            ),
            (
                "cost",
                "missing_run_cost_producer",
                "Monetary cost is not durably produced for this run.",
            ),
            (
                "cache_attribution",
                "missing_run_cache_attribution_producer",
                "Cache hits/misses are not durably correlated to this run.",
            ),
            (
                "regression_indicator",
                "missing_regression_baseline_producer",
                "No durable quality baseline comparison exists for this run.",
            ),
        ):
            metrics[name] = _unsupported(producer=producer, source="none", reason=reason)
        return metrics
