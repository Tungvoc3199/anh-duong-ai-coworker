# Value / Native Capability Gate

Use this before implementing a new feature, automation, integration, or custom tool. It prevents building commodity capability that a provider already supplies and keeps work tied to user value and measurable outcomes.

## Hard gates

- `user_value`: the real user problem solved.
- `measurement`: evidence that proves the outcome improved.
- `native_capability`: documented audit of upstream coverage and the selected decision.
- Native decisions are ordered: `USE_NATIVE` → `WRAP_NATIVE` → `EXTEND_NATIVE` → `BUILD_CUSTOM`.
- `BUILD_CUSTOM` is denied when native coverage is `>=80%` and the missing behavior is not an Ánh Dương-owned contract.

## Required outcome signals

`revenue_link` and `content_proof` are required alongside `user_value` and `measurement` for every value-gated work type. Safety/compliance/repair work uses its own non-value-gated checkpoint types rather than weakening these fields.

## Manifest example

```json
{
  "user_value": "Reduce human babysitting while completing work safely.",
  "measurement": "Human intervention minutes and verified completion rate.",
  "revenue_link": "DIRECT_REVENUE",
  "content_proof": "Before/after demo with evidence.",
  "native_capability": {
    "decision": "WRAP_NATIVE",
    "coverage_pct": 90,
    "owned_contract": false,
    "rationale": "Use native execution; keep governance and outcome verification in Ánh Dương."
  }
}
```

The standalone command below previews the decision without opening a checkpoint:

`python3 scripts/ade_os.py value-gate --manifest value-gate.json`

The authoritative mutation path is `checkpoint start`. Its evidence must include `checkpoint_id` and `work_type`; value-gated work types also include the same object under `value_gate`. A successful start records active checkpoint state. PreToolUse denies mutation-capable tools when no active checkpoint exists, and denies value-gated work unless that recorded status is `ALLOW`.

Example start evidence:

```json
{
  "checkpoint_id": "AD-FEATURE-X",
  "work_type": "feature",
  "value_gate": {
    "user_value": "Reduce human babysitting while completing work safely.",
    "measurement": "Verified completion rate.",
    "revenue_link": "INDIRECT_REVENUE",
    "content_proof": "Before/after demo with evidence.",
    "native_capability": {
      "decision": "WRAP_NATIVE",
      "coverage_pct": 90,
      "owned_contract": false,
      "rationale": "Use native execution; keep governance in Ánh Dương."
    }
  }
}
```

Run: `python3 scripts/ade_os.py checkpoint start --evidence start.json`.
