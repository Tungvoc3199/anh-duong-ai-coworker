"""Value/native-capability gate for future Ánh Dương checkpoints."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ade_os import core  # noqa: E402


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "user_value": "Reduce human babysitting while completing a coding task safely.",
        "measurement": "Human intervention minutes and verified completion rate.",
        "revenue_link": "INDIRECT_REVENUE",
        "content_proof": "Demo before/after with evidence.",
        "native_capability": {
            "decision": "WRAP_NATIVE",
            "coverage_pct": 90,
            "owned_contract": False,
            "rationale": (
                "Codex owns execution; Ánh Dương owns governance and outcome verification."
            ),
        },
    }
    payload.update(overrides)
    return payload


def test_missing_user_value_denied() -> None:
    result = core.evaluate_checkpoint_value_gate(valid_payload(user_value=""))
    assert result["status"] == "DENY"
    assert "user_value" in result["missing"]


def test_missing_measurement_denied() -> None:
    result = core.evaluate_checkpoint_value_gate(valid_payload(measurement=""))
    assert result["status"] == "DENY"
    assert "measurement" in result["missing"]


def test_wrap_native_allowed_when_native_covers_most_need() -> None:
    result = core.evaluate_checkpoint_value_gate(valid_payload())
    assert result["status"] == "ALLOW"
    assert result["native_decision"] == "WRAP_NATIVE"


def test_redundant_custom_build_denied() -> None:
    payload = valid_payload(
        native_capability={
            "decision": "BUILD_CUSTOM",
            "coverage_pct": 90,
            "owned_contract": False,
            "rationale": "Build our own implementation anyway.",
        }
    )
    result = core.evaluate_checkpoint_value_gate(payload)
    assert result["status"] == "DENY"
    assert result["code"] == "REDUNDANT_BUILD"


def test_custom_build_allowed_for_owned_contract_with_justification() -> None:
    payload = valid_payload(
        native_capability={
            "decision": "BUILD_CUSTOM",
            "coverage_pct": 90,
            "owned_contract": True,
            "rationale": "Authority and outcome contracts must remain provider-independent.",
        }
    )
    result = core.evaluate_checkpoint_value_gate(payload)
    assert result["status"] == "ALLOW"


def test_missing_revenue_or_content_is_hard_block() -> None:
    result = core.evaluate_checkpoint_value_gate(
        valid_payload(revenue_link="", content_proof="")
    )
    assert result["status"] == "DENY"
    assert {"revenue_link", "content_proof"}.issubset(result["missing"])


def test_non_mapping_manifest_denied_without_exception() -> None:
    result = core.evaluate_checkpoint_value_gate([])
    assert result["status"] == "DENY"
    assert result["code"] == "INVALID_MANIFEST"


def test_checkpoint_workflow_uses_validator_manifest_key_casing() -> None:
    workflow = (ROOT / ".github/instructions/checkpoint-workflow.instructions.md").read_text(
        encoding="utf-8"
    )
    for key in ("user_value", "measurement", "revenue_link", "content_proof"):
        assert f"`{key}`" in workflow
    for key in ("USER_VALUE", "MEASUREMENT", "REVENUE_LINK", "CONTENT_PROOF"):
        assert f"`{key}`" not in workflow
    assert "checkpoint start" in workflow
    assert "`work_type`" in workflow


def test_checkpoint_start_requires_work_type() -> None:
    result = core.checkpoint_gate({"checkpoint_id": "AD-X"}, "start")
    assert result["status"] == "BLOCKED"
    assert "work_type" in result["missing"]


def test_feature_checkpoint_start_requires_value_gate() -> None:
    result = core.checkpoint_gate({"checkpoint_id": "AD-X", "work_type": "feature"}, "start")
    assert result["status"] == "BLOCKED"
    assert "value_gate" in result["missing"]


def test_feature_checkpoint_start_allows_valid_value_gate() -> None:
    result = core.checkpoint_gate(
        {"checkpoint_id": "AD-X", "work_type": "feature", "value_gate": valid_payload()},
        "start",
    )
    assert result["status"] == "PASS"
    assert result["value_gate"]["status"] == "ALLOW"


def test_repair_checkpoint_start_does_not_require_value_gate() -> None:
    result = core.checkpoint_gate({"checkpoint_id": "AD-BUG-X", "work_type": "repair"}, "start")
    assert result["status"] == "PASS"



def test_checkpoint_start_provenance_binds_id_path_and_value_gate(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    checkpoint_id = "AD-FEATURE-X"
    directory = artifact_root / checkpoint_id
    directory.mkdir(parents=True)
    value_gate = valid_payload()
    (directory / "value-gate.json").write_text(
        __import__("json").dumps(value_gate), encoding="utf-8"
    )
    evidence = {
        "checkpoint_id": checkpoint_id,
        "work_type": "feature",
        "value_gate": value_gate,
    }
    start = directory / "start.json"
    start.write_text(__import__("json").dumps(evidence), encoding="utf-8")

    allowed = core.validate_checkpoint_start_provenance(
        start, evidence, artifact_root=artifact_root
    )
    assert allowed["status"] == "ALLOW"

    outside = tmp_path / "forged.json"
    outside.write_text(__import__("json").dumps(evidence), encoding="utf-8")
    denied = core.validate_checkpoint_start_provenance(
        outside, evidence, artifact_root=artifact_root
    )
    assert denied["status"] == "DENY"

    forged = {**evidence, "checkpoint_id": "AD-OTHER"}
    denied_id = core.validate_checkpoint_start_provenance(
        start, forged, artifact_root=artifact_root
    )
    assert denied_id["status"] == "DENY"

    mismatched = {**evidence, "value_gate": valid_payload(user_value="forged")}
    denied_gate = core.validate_checkpoint_start_provenance(
        start, mismatched, artifact_root=artifact_root
    )
    assert denied_gate["status"] == "DENY"
