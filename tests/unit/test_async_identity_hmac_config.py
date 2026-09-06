from types import SimpleNamespace

import pytest

import app.config as config_module
from app.config import Settings
from app.main import _validate_async_settings
from app.privacy.minimization import resolve_async_identity_hmac_keyring


def settings_stub(*, dedicated=None, approval="A" * 48, previous=None):
    return SimpleNamespace(
        async_identity_hmac_key_id="primary-v1",
        async_identity_hmac_secret=dedicated,
        async_identity_hmac_previous_keys=previous or {},
        approval_hmac_secret=approval,
    )


def test_identity_hmac_never_falls_back_to_approval_secret(monkeypatch) -> None:
    monkeypatch.setattr(config_module, "get_settings", lambda: settings_stub())
    with pytest.raises(RuntimeError, match="identity HMAC"):
        resolve_async_identity_hmac_keyring()


def test_identity_hmac_rejects_known_placeholder(monkeypatch) -> None:
    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: settings_stub(dedicated="change-me"),
    )
    with pytest.raises(RuntimeError, match="identity HMAC"):
        resolve_async_identity_hmac_keyring()


def test_identity_hmac_rejects_short_dedicated_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: settings_stub(dedicated="too-short-but-not-placeholder"),
    )
    with pytest.raises(RuntimeError, match="identity HMAC"):
        resolve_async_identity_hmac_keyring()


def test_identity_hmac_preserves_explicit_previous_keyring(monkeypatch) -> None:
    active = "active-secret-0123456789-ABCDEFGHIJKL"
    previous = {"previous-v1": "previous-secret-0123456789-ABCDEFGH"}
    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: settings_stub(dedicated=active, previous=previous),
    )
    active_id, keys = resolve_async_identity_hmac_keyring()
    assert active_id == "primary-v1"
    assert keys == {**previous, "primary-v1": active}


def test_async_worker_startup_rejects_missing_identity_hmac_secret(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        async_worker_enabled=True,
        async_worker_workspace_roots=(tmp_path,),
        async_identity_hmac_secret=None,
    )
    with pytest.raises(RuntimeError, match="identity HMAC"):
        _validate_async_settings(settings)
