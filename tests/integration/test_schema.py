from sqlalchemy import inspect

EXPECTED_TABLES = {
    "projects",
    "project_phases",
    "tasks",
    "workflows",
    "workflow_steps",
    "approvals",
    "memories",
    "memory_links",
    "memory_consolidation_jobs",
    "skills",
    "skill_executions",
    "persona_versions",
    "policy_versions",
    "audit_events",
}


def test_initial_migration_contains_required_tables(migrated_engine) -> None:
    tables = set(inspect(migrated_engine).get_table_names())
    assert EXPECTED_TABLES.issubset(tables)


def test_required_indexes_exist(migrated_engine) -> None:
    inspector = inspect(migrated_engine)
    project_indexes = inspector.get_indexes("projects")
    task_indexes = inspector.get_indexes("tasks")
    workflow_indexes = inspector.get_indexes("workflows")
    approval_indexes = inspector.get_indexes("approvals")

    assert any(index["name"] == "ix_projects_slug" for index in project_indexes)
    assert any(index["name"] == "ix_tasks_status" for index in task_indexes)
    assert any(index["name"] == "ix_workflows_status" for index in workflow_indexes)
    assert any(index["name"] == "ix_approvals_status" for index in approval_indexes)
