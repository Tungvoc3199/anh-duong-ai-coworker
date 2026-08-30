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
            : route === "memory"
              ? "memory_search"
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
    const body = init?.body ? JSON.parse(init.body) : undefined;
    if (url.endsWith("/prepare")) {
      return new Response(
        JSON.stringify(responseFixture(body.request_id, { route: "workflow" })),
        { status: 200 },
      );
    }
    if (url.endsWith("/api/async-tasks/run_wr1")) {
      return new Response(JSON.stringify({ status: "running" }), { status: 200 });
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
  const hooks = createAnhDuongCoreHooks({
    env: ENV,
    fetchImpl,
    logger,
    workflowProgressDelayMs: 0,
  });
  const ctx = telegramContext("run-workflow");

  const first = await hooks.beforeAgentReply({ cleanedBody: "create task" }, ctx);
  const duplicateHookCall = await hooks.beforeAgentReply({ cleanedBody: "create task" }, ctx);

  assert.deepEqual(calls, [
    "http://core.local:8790/api/internal/requests/prepare",
    "http://core.local:8790/api/async-tasks",
    "http://core.local:8790/api/async-tasks/run_wr1",
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
    reason: "anh_duong_workflow_progress_after_threshold",
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

test("workflow that reaches terminal status before progress threshold sends no progress reply", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(url);
    const body = init?.body ? JSON.parse(init.body) : undefined;
    if (url.endsWith("/prepare")) {
      return new Response(
        JSON.stringify(responseFixture(body.request_id, { route: "workflow" })),
        { status: 200 },
      );
    }
    if (url.endsWith("/api/async-tasks")) {
      return new Response(
        JSON.stringify({
          task_id: "task_fast",
          run_id: "run_fast",
          status: "pending",
          message: "ACCEPTED",
          replayed: false,
        }),
        { status: 202 },
      );
    }
    if (url.endsWith("/api/async-tasks/run_fast")) {
      return new Response(JSON.stringify({ status: "completed" }), { status: 200 });
    }
    throw new Error(`unexpected URL ${url}`);
  };
  const hooks = createAnhDuongCoreHooks({
    env: ENV,
    fetchImpl,
    workflowProgressDelayMs: 10,
    sleep: async () => {},
  });

  const result = await hooks.beforeAgentReply(
    { cleanedBody: "create task" },
    telegramContext("run-fast-workflow"),
  );

  assert.deepEqual(result, {
    handled: true,
    reason: "anh_duong_workflow_completed_before_progress",
  });
  assert.deepEqual(calls, [
    "http://core.local:8790/api/internal/requests/prepare",
    "http://core.local:8790/api/async-tasks",
    "http://core.local:8790/api/async-tasks/run_fast",
  ]);
});

test("workflow still pending after progress threshold sends progress reply", async () => {
  const calls = [];
  let slept = 0;
  const fetchImpl = async (url, init) => {
    calls.push(url);
    const body = init?.body ? JSON.parse(init.body) : undefined;
    if (url.endsWith("/prepare")) {
      return new Response(
        JSON.stringify(responseFixture(body.request_id, { route: "workflow" })),
        { status: 200 },
      );
    }
    if (url.endsWith("/api/async-tasks")) {
      return new Response(
        JSON.stringify({
          task_id: "task_slow",
          run_id: "run_slow",
          status: "pending",
          message: "ACCEPTED",
          replayed: false,
        }),
        { status: 202 },
      );
    }
    if (url.endsWith("/api/async-tasks/run_slow")) {
      return new Response(JSON.stringify({ status: "running" }), { status: 200 });
    }
    throw new Error(`unexpected URL ${url}`);
  };
  const hooks = createAnhDuongCoreHooks({
    env: ENV,
    fetchImpl,
    workflowProgressDelayMs: 25,
    sleep: async (ms) => {
      slept += ms;
    },
  });

  const result = await hooks.beforeAgentReply(
    { cleanedBody: "create task" },
    telegramContext("run-slow-workflow"),
  );

  assert.equal(slept, 25);
  assert.deepEqual(result, {
    handled: true,
    reply: { text: WORKFLOW_ACKNOWLEDGMENT },
    reason: "anh_duong_workflow_progress_after_threshold",
  });
  assert.deepEqual(calls, [
    "http://core.local:8790/api/internal/requests/prepare",
    "http://core.local:8790/api/async-tasks",
    "http://core.local:8790/api/async-tasks/run_slow",
  ]);
});

test("blocked async submit is handled without workflow acknowledgment", async () => {
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
        task_id: "task_blocked",
        run_id: "run_blocked",
        status: "blocked",
        message: "approval_required: This action requires approval.",
        replayed: false,
      }),
      { status: 202 },
    );
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const result = await hooks.beforeAgentReply(
    { cleanedBody: "create task" },
    telegramContext("run-blocked-workflow"),
  );

  assert.deepEqual(calls, [
    "http://core.local:8790/api/internal/requests/prepare",
    "http://core.local:8790/api/async-tasks",
  ]);
  assert.deepEqual(result, {
    handled: true,
    reason: "anh_duong_workflow_blocked",
  });
  assert.equal(result.reply, undefined);
});

test("DR-1R replay preserves internal IDs without duplicate task, run, or acknowledgment", async () => {
  const calls = [];
  const logger = collectingLogger();
  const fetchImpl = async (url, init) => {
    calls.push(url);
    const body = init?.body ? JSON.parse(init.body) : undefined;
    if (url.endsWith("/prepare")) {
      return new Response(
        JSON.stringify(responseFixture(body.request_id, { route: "workflow" })),
        { status: 200 },
      );
    }
    if (url.endsWith("/api/async-tasks/run_wr1")) {
      return new Response(JSON.stringify({ status: "running" }), { status: 200 });
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
  const hooks = createAnhDuongCoreHooks({
    env: ENV,
    fetchImpl,
    workflowProgressDelayMs: 0,
  });
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
    ["before_agent_reply", "before_prompt_build", "before_agent_run", "before_tool_call", "agent_end"],
  );
  assert.ok(registrations[0].options.timeoutMs > 0);
  assert.ok(registrations[1].options.timeoutMs > 0);
  assert.ok(registrations[2].options.timeoutMs > 0);
});

test("DR-1R official pre-run context uses the human workflow acknowledgment", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(url);
    const body = init?.body ? JSON.parse(init.body) : undefined;
    if (url.endsWith("/prepare")) {
      return new Response(
        JSON.stringify(responseFixture(body.request_id, { route: "workflow" })),
        { status: 200 },
      );
    }
    if (url.endsWith("/api/async-tasks/run_wr1")) {
      return new Response(JSON.stringify({ status: "running" }), { status: 200 });
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
  const hooks = createAnhDuongCoreHooks({
    env: ENV,
    fetchImpl,
    workflowProgressDelayMs: 0,
  });
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
    "http://core.local:8790/api/async-tasks/run_wr1",
  ]);
  assert.equal(first.handled, true);
  assert.equal(first.reason, "anh_duong_workflow_progress_after_threshold");
  assert.equal(first.reply.text, WORKFLOW_ACKNOWLEDGMENT);
  assert.equal(first.reply.text.includes("task_"), false);
  assert.equal(first.reply.text.includes("run_"), false);
  assert.deepEqual(duplicateHookCall, {
    handled: true,
    reason: "anh_duong_workflow_duplicate_hook",
  });
});

test("image caption fallback reuses prepared direct session state without a second prepare", async () => {
  let calls = 0;
  const fetchImpl = async (_url, init) => {
    calls += 1;
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id)), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const imageTurn = telegramContext("run-image-turn");
  await hooks.beforePromptBuild({ prompt: "ảnh này có gì", messages: [] }, imageTurn);

  const mediaReply = telegramContext("run-media-reply");
  mediaReply.sessionKey = "media-derived-session";
  const reply = await hooks.beforeAgentReply(
    { cleanedBody: "ảnh này có gì\n[Image understood: a flower]" },
    mediaReply,
  );

  assert.equal(reply, undefined);
  assert.equal(calls, 1);
  assert.deepEqual(await hooks.beforeAgentRun({}, imageTurn), { outcome: "pass" });
});

test("image understanding marker is excluded from Core routing", async () => {
  const prompts = [];
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    prompts.push(body.text);
    return new Response(JSON.stringify(responseFixture(body.request_id)), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });

  const reply = await hooks.beforeAgentReply(
    { cleanedBody: "ảnh này có gì\n[Image understood: a flower]" },
    telegramContext("run-image-marker"),
  );

  assert.equal(reply, undefined);
  assert.deepEqual(prompts, ["ảnh này có gì"]);
});

test("OpenClaw image summary envelope routes only its caption through Core", async () => {
  const prompts = [];
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    prompts.push(body.text);
    return new Response(JSON.stringify(responseFixture(body.request_id)), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });

  const reply = await hooks.beforeAgentReply(
    {
      cleanedBody:
        "[Image] User text: [Telegram user id:123] user: ảnh này có gì. Description: Ảnh chụp màn hình yêu cầu điều tra ai sửa file plugin.",
    },
    telegramContext("run-image-envelope"),
  );

  assert.equal(reply, undefined);
  assert.deepEqual(prompts, ["ảnh này có gì"]);
});

test("before_prompt_build image envelope must route direct and pass the run gate", async () => {
  const prompts = [];
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    prompts.push(body.text);
    const route = body.text.includes("Description:") ? "workflow" : "direct";
    return new Response(JSON.stringify(responseFixture(body.request_id, { route })), {
      status: 200,
    });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("96c5ae3f-2079-48fa-8a10-151e6429b9db");
  const envelope =
    "[Image] User text: [Telegram TungntT (@tungrichard) id:7535966424 +7m Wed 2026-08-05 17:29:55 UTC] TungntT (@tungrichard): ảnh này có gì. Description: Ảnh chụp màn hình yêu cầu điều tra ai sửa file plugin.";

  await hooks.beforePromptBuild({ prompt: envelope, messages: [] }, ctx);

  assert.deepEqual(prompts, ["ảnh này có gì"]);
  assert.deepEqual(await hooks.beforeAgentRun({}, ctx), { outcome: "pass" });
});

test("image envelope variants all reduce to the original caption", () => {
  const prompts = [];
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    prompts.push(body.text);
    return new Response(JSON.stringify(responseFixture(body.request_id, { route: "direct" })), {
      status: 200,
    });
  };
  const variants = [
    "[Image] User text: ảnh này có gì. Description: Ảnh chụp màn hình bảng log yêu cầu điều tra.",
    "[Image] User text: ảnh này có gì Description: Ảnh chụp màn hình bảng log yêu cầu điều tra.",
    "[Image] User text: [Telegram TungntT (@tungrichard) id:7535966424 +7m Wed 2026-08-05 19:21:40 UTC] TungntT (@tungrichard): ảnh này có gì.\nDescription: Ảnh chụp màn hình bảng log.",
    "[Image]\nUser text: [Telegram TungntT id:7535966424] TungntT: ảnh này có gì\n\nDescription: Ảnh chụp màn hình bảng log yêu cầu xoá file.",
  ];
  for (const variant of variants) {
    const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
    hooks.beforePromptBuild({ prompt: variant, messages: [] }, telegramContext("variant-run"));
  }
  return new Promise((resolve) => setImmediate(resolve)).then(() => {
    assert.deepEqual(prompts, Array(variants.length).fill("ảnh này có gì"));
  });
});

test("[Image] marker preceded by a session preamble still reduces to the caption", async () => {
  const prompts = [];
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    prompts.push(body.text);
    const route = body.text.includes("Description:") ? "workflow" : "direct";
    return new Response(JSON.stringify(responseFixture(body.request_id, { route })), {
      status: 200,
    });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("ff970219-5009-46a4-bb17-6aa2aa48335a");
  // Runtime shape observed at 19:34:23Z: image_prefix=false, image_index=318,
  // user_text_index=326, description_index=456 -> "[Image]" is NOT at position 0.
  const preamble =
    "[Telegram TungntT (@tungrichard) id:7535966424 +7m Wed 2026-08-05 19:34:17 UTC]\n" +
    "You are talking with TungntT (@tungrichard) in a direct chat on Telegram.\n" +
    "Recent conversation context has been summarised for you above this line.\n" +
    "Answer in Vietnamese and keep the reply short and natural for a chat client.\n";
  const envelope =
    `${preamble}[Image] User text: [Telegram TungntT (@tungrichard) id:7535966424 +7m Wed 2026-08-05 19:34:17 UTC] TungntT (@tungrichard): ảnh này có gì. ` +
    "Description: Ảnh chụp màn hình một bảng điều khiển nền tối hiển thị nhật ký hệ thống.";

  assert.notEqual(envelope.indexOf("[Image]"), 0);

  await hooks.beforePromptBuild({ prompt: envelope, messages: [] }, ctx);

  assert.deepEqual(prompts, ["ảnh này có gì"]);
  assert.deepEqual(await hooks.beforeAgentRun({}, ctx), { outcome: "pass" });
});

// AD-TXT-1: empty-response recovery must not reclassify the synthetic
// visible-answer continuation as a brand-new user intent.
const EMPTY_RESPONSE_RETRY_INSTRUCTION =
  "The previous attempt did not produce a user-visible answer. " +
  "Continue from the current state and produce the visible answer now. " +
  "Do not restart from scratch.";

test("synthetic empty-response continuation reuses the prepared direct state", async () => {
  const routes = [];
  let calls = 0;
  const fetchImpl = async (url, init) => {
    calls += 1;
    const body = JSON.parse(init.body);
    // Core would classify the appended continuation as a system operation.
    const route = body.text.includes("Do not restart from scratch") ? "workflow" : "direct";
    routes.push(route);
    return new Response(JSON.stringify(responseFixture(body.request_id, { route })), {
      status: 200,
    });
  };

  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("273665db-92dd-4e22-a099-567e33708827");
  const userText = "Sao đấy nhé";

  await hooks.beforePromptBuild({ prompt: userText, messages: [] }, ctx);
  assert.deepEqual(await hooks.beforeAgentRun({}, ctx), { outcome: "pass" });

  // Provider returned an empty visible answer -> gateway retries on the SAME runId
  // with the continuation appended to the original prompt.
  await hooks.beforePromptBuild(
    { prompt: `${userText}\n\n${EMPTY_RESPONSE_RETRY_INSTRUCTION}`, messages: [] },
    ctx,
  );

  // The retry must not be re-prepared, must not become a workflow, must not block.
  assert.equal(calls, 1, "continuation must not trigger a second Core prepare");
  assert.ok(!routes.includes("workflow"), "continuation must not route to workflow");
  assert.deepEqual(await hooks.beforeAgentRun({}, ctx), { outcome: "pass" });
});

// AD-TXT-1 regression (production shape): the observed failure required the
// per-run state to be unreachable at retry time, which let Core re-classify the
// synthetic continuation as system_operation and downgraded an approved
// conversational turn into a blocked workflow.
test("continuation recovers original intent when run state was torn down", async () => {
  const routes = [];
  const texts = [];
  const fetchImpl = async (url, init) => {
    const body = JSON.parse(init.body);
    texts.push(body.text);
    const route = body.text.includes("Do not restart from scratch") ? "workflow" : "direct";
    routes.push(route);
    return new Response(JSON.stringify(responseFixture(body.request_id, { route })), {
      status: 200,
    });
  };

  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("273665db-92dd-4e22-a099-567e33708827");
  const userText = "Sao đấy nhé";

  await hooks.beforePromptBuild({ prompt: userText, messages: [] }, ctx);
  assert.deepEqual(await hooks.beforeAgentRun({}, ctx), { outcome: "pass" });

  // Simulate the run teardown that made the prepared state unreachable.
  await hooks.agentEnd({}, ctx);

  await hooks.beforePromptBuild(
    { prompt: `${userText}\n\n${EMPTY_RESPONSE_RETRY_INSTRUCTION}`, messages: [] },
    ctx,
  );

  assert.ok(
    !routes.includes("workflow"),
    "synthetic continuation must never be classified as a workflow",
  );
  assert.ok(
    !texts.some((text) => text.includes("Do not restart from scratch")),
    "the retry control instruction must never be sent to Core as user intent",
  );
  assert.deepEqual(await hooks.beforeAgentRun({}, ctx), { outcome: "pass" });
});

// AD-TXT-1 guard: a genuine new system-operation request in the same session
// must still route to workflow and still fail closed. The continuation handling
// must not become a bypass for real execution requests.
test("real system operation still routes workflow after a conversational turn", async () => {
  const routes = [];
  const fetchImpl = async (url, init) => {
    const body = JSON.parse(init.body);
    const route = body.text.includes("restart the service") ? "workflow" : "direct";
    routes.push(route);
    return new Response(JSON.stringify(responseFixture(body.request_id, { route })), {
      status: 200,
    });
  };

  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-conversational");

  await hooks.beforePromptBuild({ prompt: "Sao đấy nhé", messages: [] }, ctx);
  assert.deepEqual(await hooks.beforeAgentRun({}, ctx), { outcome: "pass" });

  // A brand-new, genuinely imperative request on a fresh run.
  const workflowCtx = telegramContext("run-real-workflow");
  await hooks.beforePromptBuild({ prompt: "Please restart the service now", messages: [] }, workflowCtx);

  assert.ok(routes.includes("workflow"), "a real system operation must route to workflow");
  assert.equal(
    (await hooks.beforeAgentRun({}, workflowCtx)).outcome,
    "block",
    "workflow routes must still fail closed at the run gate",
  );
});

test("direct Telegram turns block all agent tool calls after Core classifies execution_required=false", async () => {
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id, { route: "direct" })), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-direct-tool-guard");

  await hooks.beforePromptBuild({ prompt: "xong chưa?", messages: [] }, ctx);
  assert.deepEqual(await hooks.beforeAgentRun({}, ctx), { outcome: "pass" });
  const toolCtx = { runId: ctx.runId, sessionKey: ctx.sessionKey, sessionId: "tool-session", channelId: "7535966424", toolName: "memory_search" };
  assert.deepEqual(await hooks.beforeToolCall({ toolName: "memory_search", params: {} }, toolCtx), {
    block: true,
    blockReason: "anh_duong_direct_turn_no_tools",
  });
  assert.deepEqual(await hooks.beforeToolCall({ toolName: "exec", params: { command: "ps aux" } }, { ...toolCtx, toolName: "exec" }), {
    block: true,
    blockReason: "anh_duong_direct_turn_no_tools",
  });
});

test("workflow Telegram turns do not get blocked by the direct-turn tool guard", async () => {
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id, { route: "workflow" })), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-workflow-tool-guard");

  await hooks.beforePromptBuild({ prompt: "chạy pytest", messages: [] }, ctx);
  const toolCtx = { runId: ctx.runId, sessionKey: ctx.sessionKey, sessionId: "tool-session", channelId: "7535966424", toolName: "exec" };
  assert.equal(await hooks.beforeToolCall({ toolName: "exec", params: { command: "pytest" } }, toolCtx), undefined);
});

test("memory Telegram turns allow the memory capability tools instead of the direct zero-tool guard", async () => {
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id, { route: "memory" })), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-memory-tool-guard");

  const prepared = await hooks.beforePromptBuild({ prompt: "Tìm trong bộ nhớ xem tôi đã nói gì", messages: [] }, ctx);
  assert.match(prepared.prependContext, /route: memory/);
  assert.match(prepared.prependContext, /capability: memory_search/);
  assert.deepEqual(await hooks.beforeAgentRun({}, ctx), { outcome: "pass" });
  const toolCtx = { runId: ctx.runId, sessionKey: ctx.sessionKey, sessionId: "tool-session", channelId: "7535966424" };

  assert.equal(await hooks.beforeToolCall({ toolName: "memory_search", params: {} }, { ...toolCtx, toolName: "memory_search" }), undefined);
  assert.equal(await hooks.beforeToolCall({ toolName: "memory_get", params: {} }, { ...toolCtx, toolName: "memory_get" }), undefined);
  assert.deepEqual(
    await hooks.beforeToolCall({ toolName: "exec", params: { command: "pwd" } }, { ...toolCtx, toolName: "exec" }),
    { block: true, blockReason: "anh_duong_memory_turn_memory_tools_only" },
  );
});

test("prepared context tells direct turns not to use tools or claim tool evidence", async () => {
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id, { route: "direct" })), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-direct-evidence-policy");

  const prepared = await hooks.beforePromptBuild({ prompt: "?", messages: [] }, ctx);
  assert.match(prepared.prependContext, /tool_policy: no_tools/);
  assert.match(prepared.prependContext, /do not claim.*tool.*executed/i);
});

test("prepared context tells memory turns to use memory evidence and treat operational facts as historical", async () => {
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id, { route: "memory" })), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-memory-evidence-policy");

  const prepared = await hooks.beforePromptBuild({ prompt: "Tìm trong bộ nhớ xem tôi đã nói gì", messages: [] }, ctx);
  assert.match(prepared.prependContext, /tool_policy: memory_tools_only/);
  assert.match(prepared.prependContext, /memory_search/);
  assert.match(prepared.prependContext, /historical/i);
  assert.match(prepared.prependContext, /current runtime/i);
});

test("core_read Telegram turns remain zero-tool and answer from prepared Core context", async () => {
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id, { route: "core_read" })), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-core-read-tool-guard");

  const prepared = await hooks.beforePromptBuild({ prompt: "trạng thái Core hiện tại", messages: [] }, ctx);
  assert.match(prepared.prependContext, /route: core_read/);
  assert.match(prepared.prependContext, /tool_policy: no_tools/);
  const toolCtx = { runId: ctx.runId, sessionKey: ctx.sessionKey, sessionId: "tool-session", channelId: "7535966424", toolName: "exec" };
  assert.deepEqual(await hooks.beforeToolCall({ toolName: "exec", params: { command: "pwd" } }, toolCtx), {
    block: true,
    blockReason: "anh_duong_core_read_turn_no_tools",
  });
});
