import assert from "node:assert/strict";
import test from "node:test";

import { buildAsyncTaskCreate, buildCoreRequest } from "../src/core-client.js";

function governedWorkflow() {
  return {
    request_id: "tg-governed-map",
    route_decision: { route: "workflow" },
    execution_required: true,
    workflow: {
      project_id: "proj_governed",
      title: "Apply a governed repair",
      goal: "Change only the assigned files and run verification.",
      mode: "build",
      priority: "high",
      risk_level: 2,
      approval_required: true,
      workspace: null,
      requested_by: "telegram:actor-hash",
      source_channel: "telegram",
      source_chat_id: "private-chat",
      source_session_id: "private-session",
      source_message_id: "governed-map",
      idempotency_key: "telegram:private-chat:governed-map",
      correlation_id: "tg-governed-map",
      constraints: ["assigned_paths_only", "review_required"],
      policy_decision: "require_approval",
      policy_rule_id: "coding.governed.require_assignment",
      policy_reason: "Coding work requires its explicit governance assignment.",
    },
  };
}

function expectedBaseMapping() {
  return {
    project_id: "proj_governed",
    title: "Apply a governed repair",
    goal: "Change only the assigned files and run verification.",
    mode: "build",
    priority: "high",
    risk_level: 2,
    approval_required: true,
    workspace: null,
    requested_by: "telegram:actor-hash",
    source_channel: "telegram",
    source_chat_id: "private-chat",
    source_session_id: "private-session",
    source_message_id: "governed-map",
    idempotency_key: "telegram:private-chat:governed-map",
    correlation_id: "tg-governed-map",
    constraints: ["assigned_paths_only", "review_required"],
  };
}

test("governed coding mapping preserves the exact assignment object and existing transport fields", () => {
  const prepared = governedWorkflow();
  const assignment = {
    checkpoint_id: "AD-L5-05",
    correlation_id: "tg-governed-map",
    workspace: "/isolated/worktree",
    manifest_digest: "a".repeat(64),
    allowed_paths: ["app/", "tests/"],
    reviewer_required: true,
    approval_required: true,
    max_semantic_repair_rounds: 2,
  };
  prepared.workflow.governed_coding = assignment;

  const mapped = buildAsyncTaskCreate(prepared);

  assert.strictEqual(mapped.governed_coding, assignment);
  assert.deepEqual(mapped.governed_coding, assignment);
  assert.deepEqual(mapped, { ...expectedBaseMapping(), governed_coding: assignment });
  assert.equal(mapped.correlation_id, prepared.workflow.correlation_id);
  assert.equal(mapped.idempotency_key, prepared.workflow.idempotency_key);
  assert.equal(mapped.workspace, null);
});

test("mapping does not invent governance or fall back to an assignment workspace", () => {
  const prepared = governedWorkflow();

  const mapped = buildAsyncTaskCreate(prepared);

  assert.deepEqual(mapped, expectedBaseMapping());
  assert.equal(Object.hasOwn(mapped, "governed_coding"), false);
  assert.equal(mapped.workspace, null);
});

test("non-code request mapping remains backward compatible and contains no governance envelope", () => {
  const mapped = buildCoreRequest({
    prompt: "Summarize the current project status",
    runId: "non-code-map",
    senderId: undefined,
    chatId: "private-chat",
    sessionKey: "private-session",
  });

  assert.deepEqual(mapped, {
    text: "Summarize the current project status",
    request_id: "tg-non-code-map",
    channel: "telegram",
    actor: "telegram:anonymous",
    source_chat_id: "private-chat",
    source_session_id: "private-session",
    source_message_id: "non-code-map",
  });
  assert.equal(Object.hasOwn(mapped, "governed_coding"), false);
  assert.equal(Object.hasOwn(mapped, "workspace"), false);
  assert.equal(Object.hasOwn(mapped, "authorization"), false);
  assert.equal(Object.hasOwn(mapped, "token"), false);
  assert.equal(Object.hasOwn(mapped, "bypass"), false);
});
