import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAsyncTaskCreate,
  buildCoreRequest,
  getAsyncTaskRun,
  parseApprovalIntent,
  prepareCoreRequest,
  submitAsyncTask,
  validateAsyncTaskAccepted,
  validatePreparedRequest,
} from "../src/core-client.js";
import { buildPreparedContext } from "../src/prompt.js";

const TOKEN = "secret-token-must-not-leak";
const CONFIG = {
  enabled: true,
  baseUrl: "http://core.local:8790",
  token: TOKEN,
  timeoutMs: 25,
};

function preparedFixture(requestId, { route = "direct", executionRequired = false } = {}) {
  return {
    request_id: requestId,
    normalized_text: "Tóm tắt trạng thái hệ thống hiện tại",
    persona: {
      version: "1",
      content_hash: "a".repeat(64),
    },
    route_decision: {
      route,
      rule_id: `route-${route}`,
      reason: "fixture route",
    },
    capability_decision: {
      capability: route === "workflow" ? "planning" : "conversational_response",
      source_route: route,
      reason_code: `capability-${route}`,
      matched_signals: [],
    },
    context: {
      sections: [],
      rendered_context: "[Persona]\nBạn là Ánh Dương.\n[Current Request]\nTóm tắt trạng thái hệ thống hiện tại",
      token_budget: {
        context_window_tokens: 16000,
        response_reserve_tokens: 3000,
        runtime_reserve_tokens: 1000,
        persona_soft_tokens: 1200,
        routing_soft_tokens: 800,
        task_soft_tokens: 3200,
        project_soft_tokens: 2400,
        memory_soft_tokens: 4400,
        usable_context_tokens: 12000,
      },
      estimated_tokens: 42,
      remaining_tokens: 11958,
      dropped_items: [],
      truncated_items: [],
      warnings: [],
      provenance: [],
    },
    project_id: route === "workflow" ? "proj_wr1" : null,
    task_id: null,
    execution_required: executionRequired,
    workflow:
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
          }
        : null,
    warnings: [],
    provenance: {
      persona_version: "1",
      persona_content_hash: "a".repeat(64),
      route_rule_id: `route-${route}`,
      capability_reason_code: `capability-${route}`,
      project_version: null,
      task_version: null,
      context_source_refs: [],
    },
    created_at: "2026-08-01T04:00:00Z",
  };
}

test("request mapping emits only the strict Core contract and pseudonymizes actor", () => {
  assert.deepEqual(
    buildCoreRequest({
      prompt: "  Tóm tắt trạng thái hệ thống hiện tại  ",
      runId: "f4f7990c-a5e1-4a65-9474-905b73ed9dc0",
      senderId: "123456789",
      chatId: "private-chat",
      sessionKey: "private-session",
    }),
    {
      text: "  Tóm tắt trạng thái hệ thống hiện tại  ",
      request_id: "tg-f4f7990c-a5e1-4a65-9474-905b73ed9dc0",
      channel: "telegram",
      actor: "telegram:15e2b0d3c33891ebb0f1ef609ec419420c20e320ce94c65fbc8c3312448eb225",
      source_chat_id: "private-chat",
      source_session_id: "private-session",
      source_message_id: "f4f7990c-a5e1-4a65-9474-905b73ed9dc0",
    },
  );
});

test("oversized run IDs become bounded deterministic correlations", () => {
  const first = buildCoreRequest({ prompt: "hello", runId: "x".repeat(300), senderId: undefined });
  const second = buildCoreRequest({ prompt: "hello", runId: "x".repeat(300), senderId: undefined });
  assert.equal(first.request_id, second.request_id);
  assert.match(first.request_id, /^tg-[0-9a-f]{64}$/);
  assert.ok(first.request_id.length <= 128);
  assert.equal(first.actor, "telegram:anonymous");
});

test("blank and oversized prompts fail closed before the network", () => {
  assert.throws(() => buildCoreRequest({ prompt: "   ", runId: "run", senderId: "sender" }));
  assert.throws(() => buildCoreRequest({ prompt: "x".repeat(20_001), runId: "run", senderId: "sender" }));
});

test("client performs one bearer-authenticated prepare POST and validates a direct response", async () => {
  const request = buildCoreRequest({ prompt: "hello", runId: "run-direct", senderId: "sender" });
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(preparedFixture(request.request_id)), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const result = await prepareCoreRequest({ config: CONFIG, request, fetchImpl });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://core.local:8790/api/internal/requests/prepare");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[0].init.body), request);
  assert.equal(result.route_decision.route, "direct");
  assert.equal(result.execution_required, false);
});

test("client accepts a consistent workflow response", async () => {
  const request = buildCoreRequest({ prompt: "create task", runId: "run-workflow", senderId: "sender" });
  const fetchImpl = async () =>
    new Response(JSON.stringify(preparedFixture(request.request_id, { route: "workflow", executionRequired: true })), {
      status: 200,
    });
  const result = await prepareCoreRequest({ config: CONFIG, request, fetchImpl });
  assert.equal(result.route_decision.route, "workflow");
  assert.equal(result.execution_required, true);
  assert.equal(result.workflow.project_id, "proj_wr1");
});

test("workflow mapping preserves Core policy and Telegram identity exactly", () => {
  const prepared = preparedFixture("tg-run-workflow", {
    route: "workflow",
    executionRequired: true,
  });

  assert.deepEqual(buildAsyncTaskCreate(prepared), {
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
    correlation_id: "tg-run-workflow",
    constraints: ["read_only", "no_service_restart"],
  });
});

test("async submit performs one authenticated POST and validates replay metadata", async () => {
  const prepared = preparedFixture("tg-run-workflow", {
    route: "workflow",
    executionRequired: true,
  });
  const payload = buildAsyncTaskCreate(prepared);
  const calls = [];
  const accepted = await submitAsyncTask({
    config: CONFIG,
    payload,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
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
    },
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://core.local:8790/api/async-tasks");
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.deepEqual(JSON.parse(calls[0].init.body), payload);
  assert.deepEqual(accepted, {
    task_id: "task_wr1",
    run_id: "run_wr1",
    status: "pending",
    message: "ACCEPTED",
    replayed: false,
  });
});

test("async run status lookup performs authenticated GET and validates status", async () => {
  const calls = [];
  const run = await getAsyncTaskRun({
    config: CONFIG,
    runId: "run_wr1",
    requestId: "tg-run-workflow",
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ status: "completed" }), { status: 200 });
    },
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://core.local:8790/api/async-tasks/run_wr1");
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(calls[0].init.body, undefined);
  assert.equal(run.status, "completed");
});

for (const status of [401, 409, 422]) {
  test(`async submit HTTP ${status} fails closed without body leakage`, async () => {
    let calls = 0;
    await assert.rejects(
      submitAsyncTask({
        config: CONFIG,
        payload: buildAsyncTaskCreate(
          preparedFixture("tg-run-workflow", {
            route: "workflow",
            executionRequired: true,
          }),
        ),
        fetchImpl: async () => {
          calls += 1;
          return new Response(`private-${TOKEN}`, { status });
        },
      }),
      (error) => {
        assert.equal(error?.status, status);
        assert.equal(calls, 1);
        assert.equal(String(error).includes(TOKEN), false);
        return true;
      },
    );
  });
}

test("async timeout and invalid response never become accepted tasks", async () => {
  const payload = buildAsyncTaskCreate(
    preparedFixture("tg-run-workflow", {
      route: "workflow",
      executionRequired: true,
    }),
  );
  await assert.rejects(
    submitAsyncTask({
      config: { ...CONFIG, timeoutMs: 5 },
      payload,
      fetchImpl: async (_url, init) => {
        await new Promise((resolve, reject) => {
          init.signal.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        });
      },
    }),
    (error) => error?.failureClass === "timeout",
  );
  assert.throws(
    () => validateAsyncTaskAccepted({ task_id: "task", status: "pending" }),
    (error) => error?.failureClass === "validation",
  );
});

for (const [status, failureClass] of [
  [401, "authentication"],
  [403, "authentication"],
  [500, "http"],
]) {
  test(`HTTP ${status} fails closed without retry or body leakage`, async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      return new Response(`private-body-${status}-${TOKEN}`, { status });
    };
    const request = buildCoreRequest({ prompt: "hello", runId: `run-${status}`, senderId: "sender-private" });
    await assert.rejects(
      prepareCoreRequest({ config: CONFIG, request, fetchImpl }),
      (error) => {
        assert.equal(error?.failureClass, failureClass);
        assert.equal(error?.status, status);
        assert.equal(calls, 1);
        const serialized = `${String(error)} ${JSON.stringify(error)}`;
        assert.equal(serialized.includes(TOKEN), false);
        assert.equal(serialized.includes(`private-body-${status}`), false);
        assert.equal(serialized.includes("sender-private"), false);
        return true;
      },
    );
  });
}

test("connection failure is classified and never retried", async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    throw new TypeError(`connect ECONNREFUSED ${TOKEN}`);
  };
  const request = buildCoreRequest({ prompt: "hello", runId: "run-connect", senderId: "sender" });
  await assert.rejects(
    prepareCoreRequest({ config: CONFIG, request, fetchImpl }),
    (error) => error?.failureClass === "connection" && calls === 1 && !String(error).includes(TOKEN),
  );
});

test("timeout aborts one request and is classified without leaking details", async () => {
  let calls = 0;
  const fetchImpl = async (_url, init) => {
    calls += 1;
    await new Promise((resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), {
        once: true,
      });
    });
  };
  const request = buildCoreRequest({ prompt: "hello", runId: "run-timeout", senderId: "sender" });
  await assert.rejects(
    prepareCoreRequest({ config: { ...CONFIG, timeoutMs: 5 }, request, fetchImpl }),
    (error) => error?.failureClass === "timeout" && calls === 1,
  );
});

test("malformed JSON fails response validation", async () => {
  const request = buildCoreRequest({ prompt: "hello", runId: "run-json", senderId: "sender" });
  await assert.rejects(
    prepareCoreRequest({
      config: CONFIG,
      request,
      fetchImpl: async () => new Response("not-json", { status: 200 }),
    }),
    (error) => error?.failureClass === "validation",
  );
});

test("request-ID mismatch and route inconsistency fail response validation", () => {
  const direct = preparedFixture("expected");
  assert.throws(
    () => validatePreparedRequest({ ...direct, request_id: "wrong" }, "expected"),
    (error) => error?.failureClass === "validation",
  );
  assert.throws(
    () => validatePreparedRequest({ ...direct, execution_required: true }, "expected"),
    (error) => error?.failureClass === "validation",
  );
  assert.throws(
    () =>
      validatePreparedRequest(
        {
          ...direct,
          capability_decision: { ...direct.capability_decision, source_route: "workflow" },
        },
        "expected",
      ),
    (error) => error?.failureClass === "validation",
  );
});

test("prepared prompt contains only explicit routing metadata and rendered Core context", () => {
  const prepared = preparedFixture("tg-run-direct");
  const context = buildPreparedContext(prepared);
  assert.match(context, /request_id: tg-run-direct/);
  assert.match(context, /route: direct/);
  assert.match(context, /capability: conversational_response/);
  assert.match(context, /execution_required: false/);
  assert.match(context, /Bạn là Ánh Dương/);
  assert.equal(context.includes(TOKEN), false);
  assert.equal(context.includes("created_at"), false);
});
test("parseApprovalIntent accepts a real-space approve command with action text", () => {
  const parsed = parseApprovalIntent(
    "approve f5c8231e880ff805cd6fe6f26e4b44ec Hãy viết một unit test",
  );
  assert.ok(parsed, "approve command should parse");
  assert.equal(parsed.approvalId, "f5c8231e880ff805cd6fe6f26e4b44ec");
  assert.equal(parsed.action, "Hãy viết một unit test");
});

test("parseApprovalIntent returns undefined for non-approve or malformed text", () => {
  assert.equal(parseApprovalIntent("tạo một unit test"), undefined);
  assert.equal(parseApprovalIntent(""), undefined);
  assert.equal(parseApprovalIntent(undefined), undefined);
  assert.equal(parseApprovalIntent(42), undefined);
});
