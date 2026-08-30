from __future__ import annotations

from app.planning.models import Plan, PlanNode, PlanNodeState


class PlanNodeScheduler:
    @staticmethod
    def state_for(plan: Plan, node_id: str) -> PlanNodeState:
        for execution in plan.node_executions:
            if execution.node_id == node_id:
                return execution.state
        return PlanNodeState.PENDING

    def ready_nodes(self, plan: Plan) -> tuple[PlanNode, ...]:
        ready: list[PlanNode] = []
        for node in plan.nodes:
            if self.state_for(plan, node.id) is not PlanNodeState.PENDING:
                continue
            if all(
                self.state_for(plan, dependency) is PlanNodeState.COMPLETED
                for dependency in node.depends_on
            ):
                ready.append(node)
        return tuple(ready)
