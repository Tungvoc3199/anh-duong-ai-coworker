from __future__ import annotations

from unittest.mock import Mock

import app.main as main_module
from app.context_builder import ContextBuilder, create_context_builder


def test_factory_creates_context_builder_without_accessing_database() -> None:
    session = Mock()

    builder = create_context_builder(session)

    assert isinstance(builder, ContextBuilder)
    session.execute.assert_not_called()


def test_create_app_registers_factory_without_invoking_it(
    monkeypatch,
) -> None:
    calls: list[object] = []

    def recording_factory(session: object) -> ContextBuilder:
        calls.append(session)
        raise AssertionError("Factory must not run during app creation")

    monkeypatch.setattr(
        main_module,
        "create_context_builder",
        recording_factory,
    )

    application = main_module.create_app()

    assert application.state.context_builder_factory is recording_factory
    assert calls == []

