"""Focused tests for ADE-OS ResultContract enforcement."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ade_os import core  # noqa: E402


def test_result_contract_critical_field_round_trip() -> None:
    payload = {
        "checkpoint_id": "AD-L5-01",
        "status": "READY_FOR_REVIEW",
        "classification": "DELTA_FAILURE",
        "artifacts": ["/mnt/f/AIOS/anh-duong-checkpoints/AD-L5-01/validation.log"],
        "production_write": False,
        "service_restart": False,
        "database_write": False,
        "release_ready": False,
        "custom": "preserved",
    }
    result = core.ResultContract.from_mapping(payload).to_mapping()
    assert result == payload


def test_result_contract_rejects_missing_checkpoint_id() -> None:
    payload = {
        "status": "READY_FOR_REVIEW",
        "classification": "DELTA_FAILURE",
        "artifacts": [],
        "production_write": False,
        "service_restart": False,
        "database_write": False,
        "release_ready": False,
    }
    with pytest.raises(core.AdeError, match="missing critical fields"):
        core.ResultContract.from_mapping(payload)


def test_result_contract_preserves_extra_fields() -> None:
    payload = {
        "checkpoint_id": "AD-L5-01",
        "status": "READY_FOR_REVIEW",
        "classification": "DELTA_FAILURE",
        "artifacts": [],
        "production_write": False,
        "service_restart": False,
        "database_write": False,
        "release_ready": False,
        "extra_key": "must_survive",
    }
    result = core.ResultContract.from_mapping(payload).to_mapping()
    assert result["extra_key"] == "must_survive"


def test_result_contract_no_silent_dropping() -> None:
    payload = {
        "checkpoint_id": "AD-L5-01",
        "status": "READY_FOR_REVIEW",
        "classification": "DELTA_FAILURE",
        "artifacts": ["/path/one", "/path/two"],
        "production_write": False,
        "service_restart": False,
        "database_write": False,
        "release_ready": False,
    }
    result = core.ResultContract.from_mapping(payload).to_mapping()
    assert len(result["artifacts"]) == 2
    for key in ("checkpoint_id", "status", "classification", "production_write",
                "service_restart", "database_write", "release_ready"):
        assert key in result, f"Critical field {key} was silently dropped"
