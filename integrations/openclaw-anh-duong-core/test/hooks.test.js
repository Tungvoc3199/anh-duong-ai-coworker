import assert from "node:assert/strict";
import test from "node:test";

import plugin from "../index.js";
import { SAFE_MESSAGE, createAnhDuongCoreHooks } from "../src/hooks.js";

const ENV = {
  ANH_DUONG_CORE_ENABLED: "true",
  ANH_DUONG_CORE_BASE_URL: "http://core.local:8790",
  ANH_DUONG_CORE_INTERNAL_TOKEN: "hook-test-token",
  ANH_DUONG_CORE_TIMEOUT_SECONDS: "1",
};

const WORKFLOW_ACKNOWLEDGMENT =
  "Em đã nhận việc và đang xử lý. Em sẽ báo lại ngay khi hoàn tất.";

function responseFixture(requestId, { route = "direct", workflowOverrides = {} } = {}) {
  const workflow =
    route === "workflow"
      ? {
          project_id: "proj_wr1",
          title: "Soạn checklist chỉ đọc",
          goal: "Soạn checklist 5 bước kiểm tra trạng thái Core.",
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
          correlation_id: requestId,
          constraints: ["read_only", "no_service_restart"],
          policy_decision: "allow",
          policy_rule_id: "risk.read_only.allow",
          policy_reason: "Read-only action is allowed by policy.",
          ...workflowOverrides,
        }
      : null;
  return {
    request_id: requestId,
    normalized_text: "hello",
    persona: { version: "1", content_hash: "b".repeat(64) },
    route_decision: { route, rule_id: `route-${route}`, reason: "fixture" },
    capability_decision: {
      capability:
        route === "workflow"
          ? "planning"
          : route === "core_read"
            ? "core_status_read"
            : "conversational_response",
      source_route: route,
      reason_code: route,
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
    project_id: workflow?.project_id ?? null,
    task_id: null,
    execution_required: route === "workflow",
    workflow,
    warnings: [],
    provenance: {
      persona_version: "1",
      persona_content_hash: "b".repeat(64),
      route_rule_id: `route-${route}`,
      capability_reason_code: route,
      project_version: workflow ? 1 : null,
      task_version: null,
      context_source_refs: [],
    },
    created_at: "2026-08-01T04:00:00Z",
  };
}

function telegramContext(runId = "run-1") {
  return {
    runId,
    messageProvider: "telegram",
    channel: "telegram",
    senderId: "private-sender",
    chatId: "private-chat",
    sessionKey: "private-session",
  };
}

function collectingLogger() {
  const entries = [];
  return {
    entries,
    info(message) {
      entries.push(String(message));
    },
    warn(message) {
      entries.push(String(message));
    },
  };
}

test("disabled integration and non-Telegram turns bypass Core and model gating", async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    throw new Error("must not run");
  };
  const disabled = createAnhDuongCoreHooks({
    env: { ANH_DUONG_CORE_ENABLED: "false" },
    fetchImpl,
  });
  assert.equal(await disabled.beforePromptBuild({ prompt: "hello", messages: [] }, telegramContext()), undefined);
  assert.equal(await disabled.beforeAgentRun({ prompt: "hello", messages: [] }, telegramContext()), undefined);

  const enabled = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const discord = { runId: "run-discord", messageProvider: "discord", channel: "discord" };
  assert.equal(await enabled.beforePromptBuild({ prompt: "hello", messages: [] }, discord), undefined);
  assert.equal(await enabled.beforeAgentRun({ prompt: "hello", messages: [] }, discord), undefined);
  assert.equal(calls, 0);
});

test("successful Telegram preparation injects context then allows model execution", async () => {
  let calls = 0;
  const fetchImpl = async (_url, init) => {
    calls += 1;
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id)), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-success");

  const injection = await hooks.beforePromptBuild({ prompt: "hello", messages: [] }, ctx);
  const gate = await hooks.beforeAgentRun({ prompt: "hello", messages: [] }, ctx);

  assert.equal(calls, 1);
  assert.match(injection.prependContext, /request_id: tg-run-success/);
  assert.deepEqual(gate, { outcome: "pass" });
});

test("DR-1R alo remains synchronous with no acknowledgment or async submit", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(url);
    const body = JSON.parse(init.body);
    assert.equal(body.text, "alo");
    assert.equal(body.source_chat_id, "private-chat");
    assert.equal(body.source_session_id, "private-session");
    assert.equal(body.source_message_id, "run-direct-reply");
    return new Response(JSON.stringify(responseFixture(body.request_id)), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-direct-reply");

  assert.equal(await hooks.beforeAgentReply({ cleanedBody: "alo" }, ctx), undefined);
  const injection = await hooks.beforePromptBuild({ prompt: "alo", messages: [] }, ctx);
  assert.deepEqual(await hooks.beforeAgentRun({ prompt: "alo", messages: [] }, ctx), {
    outcome: "pass",
  });
  assert.deepEqual(calls, ["http://core.local:8790/api/internal/requests/prepare"]);
  assert.match(injection.prependContext, /route: direct/);
});

test("DR-1R workflow acknowledges once without exposing IDs and blocks the model", async () => {
  const calls = [];
  const logger = collectingLogger();
  let submitted;
  const fetchImpl = async (url, init) => {
    calls.push(url);
    const body = JSON.parse(init.body);
    if (url.endsWith("/prepare")) {
      return new Response(
        JSON.stringify(responseFixture(body.request_id, { route: "workflow" })),
        { status: 200 },
      );
    }
    submitted = body;
    return new Response(
      JSON.stringify({
        task_id: "task_wr1",
        run_id: "run_wr1",
        status: "pending",
        message: "ACCEPTED",
        replayed: false,
      }),
      { status: 202 },
    );
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl, logger });
  const ctx = telegramContext("run-workflow");

  const first = await hooks.beforeAgentReply({ cleanedBody: "create task" }, ctx);
  const duplicateHookCall = await hooks.beforeAgentReply({ cleanedBody: "create task" }, ctx);

  assert.deepEqual(calls, [
    "http://core.local:8790/api/internal/requests/prepare",
    "http://core.local:8790/api/async-tasks",
  ]);
  assert.equal(submitted.risk_level, 0);
  assert.equal(submitted.approval_required, false);
  assert.equal(submitted.source_chat_id, "private-chat");
  assert.equal(submitted.source_session_id, "private-session");
  assert.equal(submitted.idempotency_key, "telegram:private-chat:run-workflow");
  assert.equal(submitted.correlation_id, "tg-run-workflow");
  assert.deepEqual(first, {
    handled: true,
    reply: { text: WORKFLOW_ACKNOWLEDGMENT },
    reason: "anh_duong_workflow_accepted",
  });
  for (const forbidden of ["task_", "run_", "task_wr1", "run_wr1"]) {
    assert.equal(first.reply.text.includes(forbidden), false);
  }
  const submitLog = logger.entries
    .map((entry) => JSON.parse(entry))
    .find((entry) => entry.event === "anh_duong_core_async_submit");
  assert.equal(submitLog.task_id, "task_wr1");
  assert.equal(submitLog.run_id, "run_wr1");
  assert.deepEqual(duplicateHookCall, {
    handled: true,
    reason: "anh_duong_workflow_duplicate_hook",
  });
  assert.equal(duplicateHookCall.reply, undefined);
  assert.equal(
    await hooks.beforePromptBuild({ prompt: "create task", messages: [] }, ctx),
    undefined,
  );
  assert.equal((await hooks.beforeAgentRun({}, ctx)).outcome, "block");
});

test("DR-1R replay preserves internal IDs without duplicate task, run, or acknowledgment", async () => {
  const calls = [];
  const logger = collectingLogger();
  const fetchImpl = async (url, init) => {
    calls.push(url);
    const body = JSON.parse(init.body);
    if (url.endsWith("/prepare")) {
      return new Response(
        JSON.stringify(responseFixture(body.request_id, { route: "workflow" })),
        { status: 200 },
      );
    }
    return new Response(
      JSON.stringify({
        task_id: "task_existing",
        run_id: "run_existing",
        status: "pending",
        message: "ACCEPTED",
        replayed: true,
      }),
      { status: 202 },
    );
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl, logger });
  const result = await hooks.beforeAgentReply(
    { cleanedBody: "create task" },
    telegramContext("run-workflow"),
  );

  assert.deepEqual(calls, [
    "http://core.local:8790/api/internal/requests/prepare",
    "http://core.local:8790/api/async-tasks",
  ]);
  assert.deepEqual(result, {
    handled: true,
    reason: "anh_duong_workflow_replayed",
  });
  assert.equal(result.reply, undefined);
  const submitLog = logger.entries
    .map((entry) => JSON.parse(entry))
    .find((entry) => entry.event === "anh_duong_core_async_submit");
  assert.equal(submitLog.outcome, "replayed");
  assert.equal(submitLog.task_id, "task_existing");
  assert.equal(submitLog.run_id, "run_existing");
});

for (const status of [401, 409, 422]) {
  test(`async HTTP ${status} fails closed without direct model fallback`, async () => {
    const fetchImpl = async (url, init) => {
      const body = JSON.parse(init.body);
      if (url.endsWith("/prepare")) {
        return new Response(
          JSON.stringify(responseFixture(body.request_id, { route: "workflow" })),
          { status: 200 },
        );
      }
      return new Response("private response", { status });
    };
    const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
    const ctx = telegramContext(`run-http-${status}`);

    assert.deepEqual(await hooks.beforeAgentReply({ cleanedBody: "create task" }, ctx), {
      handled: true,
      reply: { text: SAFE_MESSAGE },
      reason: "anh_duong_workflow_failed",
    });
    assert.equal((await hooks.beforeAgentRun({}, ctx)).outcome, "block");
  });
}

test("core-read preparation never enqueues an async task", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(url);
    const body = JSON.parse(init.body);
    return new Response(
      JSON.stringify(responseFixture(body.request_id, { route: "core_read" })),
      { status: 200 },
    );
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-core-read");

  assert.equal(await hooks.beforeAgentReply({ cleanedBody: "status" }, ctx), undefined);
  assert.equal(calls.length, 1);
  assert.match(
    (await hooks.beforePromptBuild({ prompt: "status", messages: [] }, ctx)).prependContext,
    /route: core_read/,
  );
});

test("pending preparation blocks before model input", async () => {
  let release;
  const fetchImpl = async (_url, init) => {
    await new Promise((resolve) => {
      release = resolve;
    });
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id)), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-pending");
  const pending = hooks.beforePromptBuild({ prompt: "hello", messages: [] }, ctx);
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(await hooks.beforeAgentRun({ prompt: "hello", messages: [] }, ctx), {
    outcome: "block",
    reason: "anh_duong_core_unavailable",
    category: "core_unavailable",
    message: SAFE_MESSAGE,
  });

  release();
  await pending;
});

for (const [name, fetchImpl] of [
  ["connection failure", async () => { throw new TypeError("ECONNREFUSED hook-test-token private-chat"); }],
  ["authentication failure", async () => new Response("private body", { status: 401 })],
  ["invalid response", async () => new Response("{}", { status: 200 })],
]) {
  test(`${name} blocks the model and emits only sanitized logs`, async () => {
    const logger = collectingLogger();
    const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl, logger });
    const ctx = telegramContext(`run-${name.replaceAll(" ", "-")}`);

    assert.equal(await hooks.beforePromptBuild({ prompt: "private prompt", messages: [] }, ctx), undefined);
    assert.deepEqual(await hooks.beforeAgentRun({ prompt: "private prompt", messages: [] }, ctx), {
      outcome: "block",
      reason: "anh_duong_core_unavailable",
      category: "core_unavailable",
      message: SAFE_MESSAGE,
    });

    const logs = logger.entries.join("\n");
    for (const forbidden of ["hook-test-token", "private-chat", "private-sender", "private-session", "private prompt", "private body", "Authorization"]) {
      assert.equal(logs.includes(forbidden), false);
    }
  });
}

test("missing run and session identifiers fails closed for an enabled Telegram turn", async () => {
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl: async () => { throw new Error("must not run"); } });
  const ctx = telegramContext(undefined);
  delete ctx.runId;
  delete ctx.sessionKey;
  assert.equal(await hooks.beforePromptBuild({ prompt: "hello", messages: [] }, ctx), undefined);
  assert.equal((await hooks.beforeAgentRun({ prompt: "hello", messages: [] }, ctx)).outcome, "block");
});

test("agent-end cleanup removes prepared state", async () => {
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id)), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-cleanup");
  await hooks.beforePromptBuild({ prompt: "hello", messages: [] }, ctx);
  assert.equal((await hooks.beforeAgentRun({ prompt: "hello", messages: [] }, ctx)).outcome, "pass");
  await hooks.agentEnd({}, ctx);
  assert.equal((await hooks.beforeAgentRun({ prompt: "hello", messages: [] }, ctx)).outcome, "block");
});

test("plugin entry registers workflow short-circuit before the three TG-1 hooks", () => {
  const registrations = [];
  plugin.register({
    logger: collectingLogger(),
    on(name, handler, options) {
      registrations.push({ name, handler, options });
    },
  });
  assert.deepEqual(
    registrations.map(({ name }) => name),
    ["before_agent_reply", "before_prompt_build", "before_agent_run", "agent_end"],
  );
  assert.ok(registrations[0].options.timeoutMs > 0);
  assert.ok(registrations[1].options.timeoutMs > 0);
  assert.ok(registrations[2].options.timeoutMs > 0);
});

test("DR-1R official pre-run context uses the human workflow acknowledgment", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(url);
    const body = JSON.parse(init.body);
    if (url.endsWith("/prepare")) {
      return new Response(
        JSON.stringify(responseFixture(body.request_id, { route: "workflow" })),
        { status: 200 },
      );
    }
    return new Response(
      JSON.stringify({
        task_id: "task_wr1",
        run_id: "run_wr1",
        status: "pending",
        message: "ACCEPTED",
        replayed: false,
      }),
      { status: 202 },
    );
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext(undefined);
  delete ctx.runId;
  ctx.sessionId = "official-session-id";

  const first = await hooks.beforeAgentReply({ cleanedBody: "create task" }, ctx);
  const duplicateHookCall = await hooks.beforeAgentReply(
    { cleanedBody: "create task" },
    ctx,
  );

  assert.deepEqual(calls, [
    "http://core.local:8790/api/internal/requests/prepare",
    "http://core.local:8790/api/async-tasks",
  ]);
  assert.equal(first.handled, true);
  assert.equal(first.reason, "anh_duong_workflow_accepted");
  assert.equal(first.reply.text, WORKFLOW_ACKNOWLEDGMENT);
  assert.equal(first.reply.text.includes("task_"), false);
  assert.equal(first.reply.text.includes("run_"), false);
  assert.deepEqual(duplicateHookCall, {
    handled: true,
    reason: "anh_duong_workflow_duplicate_hook",
  });
});
