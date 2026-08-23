import assert from "node:assert/strict";
import test from "node:test";

import plugin, {
  WORKFLOW_ACKNOWLEDGMENT,
  createPluginHandlers,
  deleteTelegramWorkflowProgress,
} from "../index.js";

test("Telegram progress cleanup uses the v2026.7.1 argv contract", async () => {
  const calls = [];
  const api = {
    runtime: {
      system: {
        async runCommandWithTimeout(...args) {
          calls.push(args);
          return { code: 0, stdout: "", stderr: "" };
        },
      },
    },
  };

  await deleteTelegramWorkflowProgress(api, {
    chatId: "private-chat",
    messageId: "3170",
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].length, 2);
  assert.deepEqual(calls[0][0], [
    process.execPath,
    "/app/openclaw.mjs",
    "message",
    "delete",
    "--channel",
    "telegram",
    "--target",
    "private-chat",
    "--message-id",
    "3170",
  ]);
  assert.deepEqual(calls[0][1], { timeoutMs: 10_000, cwd: "/app" });
});

test("workflow progress ACK is deleted after final notification is sent", async () => {
  const deleted = [];
  const scheduled = [];
  const requests = [];
  const env = {
    ANH_DUONG_CORE_ENABLED: "true",
    ANH_DUONG_CORE_BASE_URL: "http://core.local:8790",
    ANH_DUONG_CORE_INTERNAL_TOKEN: "hook-test-token",
    ANH_DUONG_CORE_TIMEOUT_SECONDS: "1",
  };
  const fetchImpl = async (url, init = {}) => {
    requests.push(String(url));
    if (String(url).endsWith("/api/internal/requests/prepare")) {
      const body = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          request_id: body.request_id,
          normalized_text: "create task",
          persona: { version: "1", content_hash: "b".repeat(64) },
          route_decision: { route: "workflow", rule_id: "route-workflow", reason: "fixture" },
          capability_decision: {
            capability: "planning",
            source_route: "workflow",
            reason_code: "workflow",
            matched_signals: [],
          },
          context: {
            sections: [],
            rendered_context: "prepared context",
            token_budget: {},
            estimated_tokens: 2,
            remaining_tokens: 100,
            dropped_items: [],
            truncated_items: [],
            warnings: [],
            provenance: [],
          },
          project_id: "proj_wr1",
          task_id: null,
          execution_required: true,
          workflow: {
            project_id: "proj_wr1",
            title: "Read-only check",
            goal: "Check health",
            mode: "quick",
            priority: "high",
            risk_level: 0,
            approval_required: false,
            workspace: "/mnt/f/AIOS/anh-duong-core",
            requested_by: "telegram:actor-hash",
            source_channel: "telegram",
            source_chat_id: "private-chat",
            source_session_id: "private-session",
            source_message_id: "run-workflow",
            idempotency_key: "telegram:private-chat:run-workflow",
            correlation_id: body.request_id,
            constraints: ["read_only"],
            policy_decision: "allow",
            policy_rule_id: "risk.read_only.allow",
            policy_reason: "Read-only action is allowed by policy.",
          },
          warnings: [],
          provenance: {
            persona_version: "1",
            persona_content_hash: "b".repeat(64),
            route_rule_id: "route-workflow",
            capability_reason_code: "workflow",
            project_version: 1,
            task_version: null,
            context_source_refs: [],
          },
          created_at: "2026-08-12T00:00:00Z",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (String(url).endsWith("/api/async-tasks")) {
      return new Response(
        JSON.stringify({
          task_id: "task_wr1",
          run_id: "run_wr1",
          status: "pending",
          message: "ACCEPTED",
          replayed: false,
        }),
        { status: 202, headers: { "content-type": "application/json" } },
      );
    }
    if (String(url).endsWith("/api/async-tasks/run_wr1")) {
      return new Response(
        JSON.stringify({ id: "run_wr1", status: "completed", notification_status: "sent" }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    throw new Error(`unexpected URL: ${url}`);
  };
  const handlers = createPluginHandlers({
    env,
    fetchImpl,
    workflowProgressDelayMs: 0,
    workflowProgressCleanupPollMs: 0,
    deleteWorkflowProgress: async (target) => {
      deleted.push(target);
    },
    scheduleWorkflowCleanup: (task) => {
      scheduled.push(task);
    },
  });
  const ctx = {
    runId: "run-workflow",
    messageProvider: "telegram",
    channel: "telegram",
    senderId: "private-sender",
    chatId: "private-chat",
    sessionKey: "private-session",
  };

  const reply = await handlers.beforeAgentReply({ cleanedBody: "create task" }, ctx);
  assert.equal(reply.reply.text, WORKFLOW_ACKNOWLEDGMENT);
  await handlers.messageSent(
    {
      to: "private-chat",
      content: WORKFLOW_ACKNOWLEDGMENT,
      success: true,
      messageId: "3202",
      sessionKey: "private-session",
    },
    { channelId: "telegram", conversationId: "private-chat", sessionKey: "private-session" },
  );
  await Promise.all(scheduled);

  assert.deepEqual(deleted, [{ chatId: "private-chat", messageId: "3202" }]);
  assert.ok(requests.includes("http://core.local:8790/api/async-tasks/run_wr1"));
});

test("plugin adds message_sent cleanup without replacing existing hooks", () => {
  const registered = new Set();
  plugin.register({
    logger: {},
    runtime: { system: { runCommandWithTimeout: async () => ({ code: 0 }) } },
    on(name) {
      registered.add(name);
    },
  });

  for (const name of [
    "before_agent_reply",
    "before_prompt_build",
    "before_agent_run",
    "agent_end",
    "message_sent",
  ]) {
    assert.ok(registered.has(name), name);
  }
});
