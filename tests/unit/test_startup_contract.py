"""Startup contract regression tests for AD-RELEASE-BLOCKER-1.

The CE-2 close commit (2915d43) accidentally introduced a cache wiring
hunk into app/main.py that references Settings.cache_* fields that do not
exist on app/config.py Settings (74c76dc).  On the release lineage this
was removed by 453fdc0 ("fix(async): remove accidental cache hunk from
CE-2 sync").  The intended runtime contract is NO cache wiring:

* create_app() must succeed without Settings.cache_* attributes
  (i.e. no AttributeError on import or app creation);
* the pipeline factory partial must not pass cache_service /
  persona_ttl_seconds / memory_retrieval_ttl_seconds kwargs that
  create_core_request_pipeline() does not accept (no TypeError);
* app.state.cache_service must not exist (no cache feature in this
  release);
* the 27-line cache hunk must be absent (byte-level guard);
* L2 must never be enabled through the current contract.

These tests FAIL on the current tree (RED) and pass after the minimal
fix, which is applying the 453fdc0 removal to app/main.py.
"""

import inspect
from pathlib import Path

from app.config import Settings
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_create_app_does_not_require_cache_settings_fields(monkeypatch) -> None:
    """create_app() must not read Settings.cache_* attributes (RED today)."""
    for name in (
        "ANH_DUONG_CACHE_ENABLED",
        "ANH_DUONG_CACHE_L1_ENABLED",
        "ANH_DUONG_CACHE_L2_ENABLED",
        "ANH_DUONG_CACHE_L1_MAX_ENTRIES_PER_NAMESPACE",
        "ANH_DUONG_CACHE_L1_MAX_BYTES_PER_NAMESPACE",
        "ANH_DUONG_CACHE_L2_MAX_PAYLOAD_BYTES",
        "ANH_DUONG_CACHE_L2_MAX_ENTRIES",
        "ANH_DUONG_CACHE_DEFAULT_TTL_SECONDS",
        "ANH_DUONG_CACHE_DB_PATH",
        "ANH_DUONG_CACHE_PERSONA_TTL_SECONDS",
        "ANH_DUONG_CACHE_MEMORY_RETRIEVAL_TTL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)
    app = create_app(settings)
    assert app is not None


def test_pipeline_factory_kwargs_match_signature(monkeypatch) -> None:
    """The factory partial must only pass kwargs wiring.py accepts."""
    from app.orchestration.wiring import create_core_request_pipeline

    signature = inspect.signature(create_core_request_pipeline)
    allowed = set(signature.parameters)
    assert "cache_service" not in allowed
    assert "persona_ttl_seconds" not in allowed
    assert "memory_retrieval_ttl_seconds" not in allowed

    settings = Settings(_env_file=None)
    app = create_app(settings)
    partial_ = app.state.core_request_pipeline_factory
    for name in (
        "cache_service",
        "persona_ttl_seconds",
        "memory_retrieval_ttl_seconds",
    ):
        assert name not in partial_.keywords


def test_no_cache_service_state(monkeypatch) -> None:
    """The app must not expose a cache_service state attribute."""
    settings = Settings(_env_file=None)
    app = create_app(settings)
    assert not hasattr(app.state, "cache_service")


def test_main_py_cache_hunk_is_absent() -> None:
    """Byte-level guard: the accidental cache hunk must be gone."""
    main_py = (REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "from app.cache.service import CacheService, CacheSettings" not in main_py
    assert "CacheSettings(" not in main_py
    assert "cache_settings" not in main_py
    assert "cache_service" not in main_py


def test_l2_never_enabled() -> None:
    """The current contract must not enable L2 in any code path."""
    main_py = (REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "cache_l2_enabled" not in main_py
    config_py = (REPO_ROOT / "app" / "config.py").read_text(encoding="utf-8")
    assert "cache_l2_enabled" not in config_py


def test_cache_service_module_still_imports() -> None:
    """Untracked cache package must remain importable (untouched by fix)."""
    import app.cache.service  # noqa: F401
    import app.memory.cached_retrieval  # noqa: F401
    import app.persona.cached_loader  # noqa: F401


def test_full_lifespan_startup_with_defaults(monkeypatch) -> None:
    """A fresh app must initialize without cache errors (no cache env)."""
    for name in (
        "ANH_DUONG_CACHE_ENABLED",
        "ANH_DUONG_CACHE_L1_ENABLED",
        "ANH_DUONG_CACHE_L2_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)
    app = create_app(settings)
    assert app.state.core_request_pipeline_factory is not None
    assert not hasattr(app.state, "cache_service")
    assert not hasattr(app.state, "cache_settings")
