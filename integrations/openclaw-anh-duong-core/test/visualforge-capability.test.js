import assert from "node:assert/strict";
import test from "node:test";

import { validatePreparedRequest } from "../src/core-client.js";

function visualPrepared(requestId) {
  const goal = 'Dùng VisualForge tạo prompt ảnh serum, text "GIẢM 50%".';
  return {
    request_id: requestId,
    normalized_text: goal,
    persona: { version: "1", content_hash: "a".repeat(64) },
    route_decision: {
      route: "workflow",
      rule_id: "route-workflow",
      reason: "visual prompt composition requires local workflow",
    },
    capability_decision: {
      capability: "visual_prompt_compose",
      source_route: "workflow",
      reason_code: "workflow.visual_prompt_compose",
      matched_signals: ["visualforge", "prompt ảnh"],
    },
    context: { rendered_context: `[Current Request]\n${goal}` },
    project_id: "proj_vf",
    task_id: null,
    execution_required: true,
    workflow: {
      project_id: "proj_vf",
      title: "Compose VisualForge prompt",
      goal,
      mode: "quick",
      priority: "high",
      risk_level: 0,
      approval_required: false,
      workspace: "/home/thadc/AIOS/visualforge",
      requested_by: "telegram:test",
      source_channel: "telegram",
      source_chat_id: "chat-vf",
      source_session_id: "session-vf",
      source_message_id: "message-vf",
      idempotency_key: "telegram:chat-vf:message-vf",
      correlation_id: requestId,
      constraints: ["read_only", "no_network"],
      policy_decision: "allow",
      policy_rule_id: "risk.read_only.allow",
      policy_reason: "Local prompt composition is read-only.",
    },
    warnings: [],
    provenance: {
      persona_version: "1",
      persona_content_hash: "a".repeat(64),
      route_rule_id: "route-workflow",
      capability_reason_code: "workflow.visual_prompt_compose",
      context_source_refs: [],
    },
    created_at: "2026-08-31T04:00:00Z",
  };
}

test("OpenClaw accepts Core visual_prompt_compose capability", () => {
  const requestId = "tg-visualforge-capability";
  const prepared = visualPrepared(requestId);
  const validated = validatePreparedRequest(prepared, requestId);
  assert.equal(validated.capability_decision.capability, "visual_prompt_compose");
});

test("OpenClaw still rejects an unregistered Core capability", () => {
  const requestId = "tg-unknown-capability";
  const prepared = visualPrepared(requestId);
  prepared.capability_decision.capability = "future_unregistered_capability";
  assert.throws(
    () => validatePreparedRequest(prepared, requestId),
    (error) => error?.failureClass === "validation",
  );
});
