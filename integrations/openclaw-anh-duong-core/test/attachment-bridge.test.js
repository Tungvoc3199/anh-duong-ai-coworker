import assert from "node:assert/strict";
import test from "node:test";

import { createPluginHandlers } from "../index.js";

const ENV = {
  ANH_DUONG_CORE_ENABLED: "true",
  ANH_DUONG_CORE_BASE_URL: "http://core.local:8790",
  ANH_DUONG_CORE_INTERNAL_TOKEN: "attachment-test-token",
  ANH_DUONG_CORE_TIMEOUT_SECONDS: "1",
};

function preparedFixture(requestId) {
  return {
    request_id: requestId,
    normalized_text: "File đây nhé",
    persona: { version: "1", content_hash: "a".repeat(64) },
    route_decision: {
      route: "direct",
      rule_id: "routing.direct.attachment_context",
      reason: "attachment context",
    },
    capability_decision: {
      capability: "conversational_response",
      source_route: "direct",
      reason_code: "attachment_context",
      matched_signals: [],
    },
    context: { rendered_context: "prepared attachment context" },
    project_id: null,
    task_id: null,
    execution_required: false,
    workflow: null,
    warnings: [],
    provenance: {
      persona_version: "1",
      persona_content_hash: "a".repeat(64),
      route_rule_id: "routing.direct.attachment_context",
      capability_reason_code: "attachment_context",
      project_version: null,
      task_version: null,
      context_source_refs: ["attachment:0"],
    },
    created_at: "2026-08-13T09:00:00Z",
  };
}

test("message_received media facts are injected into the same Core prepare request only", async () => {
  const bodies = [];
  const handlers = createPluginHandlers({
    api: { logger: {} },
    env: ENV,
    fetchImpl: async (_url, init) => {
      const body = JSON.parse(init.body);
      bodies.push(body);
      return new Response(JSON.stringify(preparedFixture(body.request_id)), { status: 200 });
    },
  });

  await handlers.messageReceived(
    {
      from: "telegram:user",
      content: "File đây nhé",
      messageId: "msg-1",
      runId: "run-1",
      sessionKey: "session-1",
      metadata: {
        mediaPath: "/tmp/openclaw/a.docx",
        mediaUrl: "media://telegram/a",
        mediaType:
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      },
    },
    {
      channelId: "telegram",
      runId: "run-1",
      sessionKey: "session-1",
      messageId: "msg-1",
    },
  );

  await handlers.beforePromptBuild(
    { prompt: "File đây nhé", messages: [] },
    {
      messageProvider: "telegram",
      runId: "run-1",
      sessionKey: "session-1",
      senderId: "sender-1",
      chatId: "chat-1",
    },
  );

  assert.equal(bodies.length, 1);
  assert.equal(bodies[0].attachments.length, 1);
  assert.equal(bodies[0].attachments[0].kind, "document");
  assert.equal(bodies[0].attachments[0].filename, "a.docx");
  assert.equal(bodies[0].attachments[0].local_ref, "/tmp/openclaw/a.docx");

  await handlers.beforePromptBuild(
    { prompt: "alo", messages: [] },
    {
      messageProvider: "telegram",
      runId: "run-2",
      sessionKey: "session-1",
      senderId: "sender-1",
      chatId: "chat-1",
    },
  );

  assert.equal(bodies.length, 2);
  assert.equal("attachments" in bodies[1], false);
});

test("session correlation carries attachment when message_received has no run id", async () => {
  const bodies = [];
  const handlers = createPluginHandlers({
    api: { logger: {} },
    env: ENV,
    fetchImpl: async (_url, init) => {
      const body = JSON.parse(init.body);
      bodies.push(body);
      return new Response(JSON.stringify(preparedFixture(body.request_id)), { status: 200 });
    },
  });

  await handlers.messageReceived(
    {
      from: "telegram:user",
      content: "File đây nhé",
      messageId: "msg-no-run",
      sessionKey: "session-no-run",
      metadata: {
        mediaPath: "/tmp/openclaw/no-run.docx",
        mediaType:
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      },
    },
    {
      channelId: "telegram",
      sessionKey: "session-no-run",
      messageId: "msg-no-run",
    },
  );

  await handlers.beforePromptBuild(
    { prompt: "File đây nhé", messages: [] },
    {
      messageProvider: "telegram",
      runId: "run-created-later",
      sessionKey: "session-no-run",
      senderId: "sender-1",
      chatId: "chat-1",
    },
  );

  assert.equal(bodies.length, 1);
  assert.equal(bodies[0].attachments.length, 1);
  assert.equal(bodies[0].attachments[0].filename, "no-run.docx");

  await handlers.beforePromptBuild(
    { prompt: "alo", messages: [] },
    {
      messageProvider: "telegram",
      runId: "run-next",
      sessionKey: "session-no-run",
      senderId: "sender-1",
      chatId: "chat-1",
    },
  );

  assert.equal(bodies.length, 2);
  assert.equal("attachments" in bodies[1], false);
});
