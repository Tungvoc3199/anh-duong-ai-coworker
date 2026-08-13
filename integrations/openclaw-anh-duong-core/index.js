import { AsyncLocalStorage } from "node:async_hooks";

import {
  WORKFLOW_ACKNOWLEDGMENT,
  createAnhDuongCoreHooks,
} from "./src/hooks.js";
import { normalizeInboundAttachmentFacts } from "./src/attachments.js";
import { getAsyncTaskRun } from "./src/core-client.js";
import { readCoreConfig } from "./src/config.js";

export { WORKFLOW_ACKNOWLEDGMENT } from "./src/hooks.js";

const PROMPT_HOOK_TIMEOUT_MS = 32_000;
const WORKFLOW_HOOK_TIMEOUT_MS = 65_000;
const GATE_HOOK_TIMEOUT_MS = 2_000;
const MESSAGE_HOOK_TIMEOUT_MS = 2_000;
const TELEGRAM_DELETE_TIMEOUT_MS = 10_000;
const WORKFLOW_PROGRESS_TTL_MS = 5 * 60_000;
const ATTACHMENT_STATE_TTL_MS = 5 * 60_000;
const WORKFLOW_PROGRESS_CLEANUP_POLL_MS = 2_000;
const WORKFLOW_PROGRESS_CLEANUP_MAX_ATTEMPTS = 900;
const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "blocked", "cancelled"]);

function safeLog(logger, level, fields) {
  const method = logger?.[level];
  if (typeof method !== "function") {
    return;
  }
  try {
    method.call(logger, JSON.stringify(fields));
  } catch {
    // Cleanup observability must never affect Telegram delivery.
  }
}

function progressKey(sessionKey, chatId) {
  if (chatId !== undefined && chatId !== null && String(chatId).length > 0) {
    return `chat:${String(chatId)}`;
  }
  if (typeof sessionKey === "string" && sessionKey.length > 0) {
    return `session:${sessionKey}`;
  }
  return undefined;
}

function runIdOf(event, ctx) {
  const value = event?.runId ?? ctx?.runId;
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function sessionKeyOf(event, ctx) {
  const value = event?.sessionKey ?? ctx?.sessionKey;
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export async function deleteTelegramWorkflowProgress(api, { chatId, messageId }) {
  const runner = api?.runtime?.system?.runCommandWithTimeout;
  if (typeof runner !== "function") {
    throw new Error("OpenClaw runtime command helper is unavailable.");
  }
  const result = await runner(
    [
      process.execPath,
      "/app/openclaw.mjs",
      "message",
      "delete",
      "--channel",
      "telegram",
      "--target",
      String(chatId),
      "--message-id",
      String(messageId),
    ],
    { timeoutMs: TELEGRAM_DELETE_TIMEOUT_MS, cwd: "/app" },
  );
  if (result?.code !== 0) {
    throw new Error("OpenClaw Telegram progress deletion failed.");
  }
}

export function createPluginHandlers({
  api,
  env = process.env,
  fetchImpl = fetch,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  workflowProgressDelayMs,
  workflowProgressCleanupPollMs = WORKFLOW_PROGRESS_CLEANUP_POLL_MS,
  workflowProgressCleanupMaxAttempts = WORKFLOW_PROGRESS_CLEANUP_MAX_ATTEMPTS,
  deleteWorkflowProgress = (target) => deleteTelegramWorkflowProgress(api, target),
  scheduleWorkflowCleanup = (task) => { void task; },
} = {}) {
  const replyContext = new AsyncLocalStorage();
  const prepareContext = new AsyncLocalStorage();
  const pendingProgress = new Map();
  const inboundAttachments = new Map();
  const pendingSessionAttachments = new Map();
  let config;
  try {
    config = readCoreConfig(env, api?.pluginConfig ?? {});
  } catch {
    config = undefined;
  }

  function sweepPending() {
    const current = Date.now();
    for (const [key, queue] of pendingProgress) {
      const retained = queue.filter((item) => item.expiresAt > current);
      if (retained.length > 0) {
        pendingProgress.set(key, retained);
      } else {
        pendingProgress.delete(key);
      }
    }
    for (const [runId, state] of inboundAttachments) {
      if (state.expiresAt <= current) {
        inboundAttachments.delete(runId);
      }
    }
    for (const [sessionKey, queue] of pendingSessionAttachments) {
      const retained = queue.filter((item) => item.expiresAt > current);
      if (retained.length > 0) {
        pendingSessionAttachments.set(sessionKey, retained);
      } else {
        pendingSessionAttachments.delete(sessionKey);
      }
    }
  }

  async function trackedFetch(url, init = {}) {
    let effectiveInit = init;
    const prepareCall = prepareContext.getStore();
    if (
      prepareCall?.attachments?.length > 0 &&
      init?.method === "POST" &&
      String(url).endsWith("/api/internal/requests/prepare") &&
      typeof init.body === "string"
    ) {
      try {
        const payload = JSON.parse(init.body);
        effectiveInit = {
          ...init,
          body: JSON.stringify({
            ...payload,
            attachments: prepareCall.attachments,
          }),
        };
      } catch {
        // Core client validation remains authoritative for malformed request bodies.
      }
    }

    const response = await fetchImpl(url, effectiveInit);
    const call = replyContext.getStore();
    if (
      call &&
      effectiveInit?.method === "POST" &&
      String(url).endsWith("/api/async-tasks") &&
      response?.ok &&
      typeof response.clone === "function"
    ) {
      try {
        const accepted = await response.clone().json();
        const payload = typeof effectiveInit.body === "string" ? JSON.parse(effectiveInit.body) : {};
        if (
          typeof accepted?.run_id === "string" &&
          accepted.run_id.length > 0 &&
          accepted.replayed !== true &&
          accepted.status !== "blocked"
        ) {
          call.accepted = {
            runId: accepted.run_id,
            requestId: payload?.correlation_id,
          };
        }
      } catch {
        // The Core hook remains authoritative for response validation.
      }
    }
    return response;
  }

  const hooks = createAnhDuongCoreHooks({
    env,
    fetchImpl: trackedFetch,
    logger: api?.logger,
    ...(workflowProgressDelayMs === undefined ? {} : { workflowProgressDelayMs }),
  });

  function rememberProgress(ctx, accepted) {
    const key = progressKey(ctx?.sessionKey, ctx?.chatId);
    if (!key) {
      return;
    }
    sweepPending();
    const queue = pendingProgress.get(key) ?? [];
    queue.push({
      ...accepted,
      chatId: ctx?.chatId,
      sessionKey: ctx?.sessionKey,
      expiresAt: Date.now() + WORKFLOW_PROGRESS_TTL_MS,
    });
    pendingProgress.set(key, queue);
  }

  function takeProgress(event, ctx) {
    sweepPending();
    const keys = [
      progressKey(ctx?.sessionKey ?? event?.sessionKey, event?.to),
      progressKey(undefined, event?.to),
    ].filter(Boolean);
    for (const key of new Set(keys)) {
      const queue = pendingProgress.get(key);
      if (!queue?.length) {
        continue;
      }
      const item = queue.shift();
      if (queue.length > 0) {
        pendingProgress.set(key, queue);
      } else {
        pendingProgress.delete(key);
      }
      return item;
    }
    return undefined;
  }

  function enqueueSessionAttachments(sessionKey, state) {
    const queue = pendingSessionAttachments.get(sessionKey) ?? [];
    queue.push(state);
    pendingSessionAttachments.set(sessionKey, queue);
  }

  function takeSessionAttachments(sessionKey) {
    const queue = pendingSessionAttachments.get(sessionKey);
    if (!queue?.length) {
      return undefined;
    }
    const state = queue.shift();
    if (queue.length > 0) {
      pendingSessionAttachments.set(sessionKey, queue);
    } else {
      pendingSessionAttachments.delete(sessionKey);
    }
    return state;
  }

  async function messageReceived(event, ctx) {
    if (ctx?.channelId !== "telegram") {
      return undefined;
    }
    sweepPending();
    const attachments = normalizeInboundAttachmentFacts(event, ctx);
    if (attachments.length === 0) {
      return undefined;
    }
    const runId = runIdOf(event, ctx);
    const sessionKey = sessionKeyOf(event, ctx);
    const state = {
      attachments,
      expiresAt: Date.now() + ATTACHMENT_STATE_TTL_MS,
    };
    if (runId) {
      inboundAttachments.set(runId, state);
    } else if (sessionKey) {
      enqueueSessionAttachments(sessionKey, state);
    } else {
      safeLog(api?.logger, "warn", {
        event: "anh_duong_core_attachment_uncorrelated",
        attachment_count: attachments.length,
        attachment_kinds: attachments.map((item) => item.kind),
      });
      return undefined;
    }
    safeLog(api?.logger, "info", {
      event: "anh_duong_core_attachment_observed",
      correlation: runId ? "run" : "session",
      attachment_count: attachments.length,
      attachment_kinds: attachments.map((item) => item.kind),
    });
    return undefined;
  }

  async function beforePromptBuild(event, ctx) {
    sweepPending();
    const runId = runIdOf(event, ctx);
    let state = runId ? inboundAttachments.get(runId) : undefined;
    if (!state) {
      const sessionKey = sessionKeyOf(event, ctx);
      if (sessionKey) {
        state = takeSessionAttachments(sessionKey);
        if (state && runId) {
          inboundAttachments.set(runId, state);
        }
      }
    }
    return prepareContext.run(
      { attachments: state?.attachments ?? [] },
      () => hooks.beforePromptBuild(event, ctx),
    );
  }

  async function beforeAgentReply(event, ctx) {
    const call = {};
    const result = await replyContext.run(call, () => hooks.beforeAgentReply(event, ctx));
    if (result?.reply?.text === WORKFLOW_ACKNOWLEDGMENT && call.accepted) {
      rememberProgress(ctx, call.accepted);
    }
    return result;
  }

  async function monitorProgress(progress, messageId) {
    if (!config?.enabled) {
      return;
    }
    const attempts = Math.max(1, Math.floor(Number(workflowProgressCleanupMaxAttempts) || 1));
    const pollMs = Math.max(0, Number(workflowProgressCleanupPollMs) || 0);
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      if (attempt > 0 && pollMs > 0) {
        await sleep(pollMs);
      }
      let run;
      try {
        run = await getAsyncTaskRun({
          config,
          runId: progress.runId,
          requestId: progress.requestId,
          fetchImpl,
        });
      } catch {
        continue;
      }
      if (TERMINAL_RUN_STATUSES.has(run.status) && run.notification_status === "sent") {
        try {
          await deleteWorkflowProgress({ chatId: progress.chatId, messageId });
          safeLog(api?.logger, "info", {
            event: "anh_duong_core_workflow_progress_cleanup",
            outcome: "deleted",
            request_id: progress.requestId,
          });
        } catch {
          safeLog(api?.logger, "warn", {
            event: "anh_duong_core_workflow_progress_cleanup",
            outcome: "failure",
            request_id: progress.requestId,
            failure_class: "delete_failed",
          });
        }
        return;
      }
      if (TERMINAL_RUN_STATUSES.has(run.status) && run.notification_status === "failed") {
        safeLog(api?.logger, "warn", {
          event: "anh_duong_core_workflow_progress_cleanup",
          outcome: "retained",
          request_id: progress.requestId,
          failure_class: "final_notification_failed",
        });
        return;
      }
    }
  }

  async function messageSent(event, ctx) {
    if (
      ctx?.channelId !== "telegram" ||
      event?.content !== WORKFLOW_ACKNOWLEDGMENT ||
      event?.success !== true ||
      event?.messageId === undefined ||
      event?.messageId === null
    ) {
      return undefined;
    }
    const progress = takeProgress(event, ctx);
    if (!progress) {
      return undefined;
    }
    scheduleWorkflowCleanup(monitorProgress(progress, String(event.messageId)));
    return undefined;
  }

  async function agentEnd(event, ctx) {
    try {
      return await hooks.agentEnd(event, ctx);
    } finally {
      const runId = runIdOf(event, ctx);
      if (runId) {
        inboundAttachments.delete(runId);
      }
    }
  }

  return {
    beforeAgentReply,
    beforePromptBuild,
    beforeAgentRun: hooks.beforeAgentRun,
    messageReceived,
    messageSent,
    agentEnd,
  };
}

export default {
  id: "anh-duong-core",
  name: "Ánh Dương Core Gate",
  description: "Fail-closed Core preparation gate for ordinary Telegram agent turns.",
  register(api) {
    const handlers = createPluginHandlers({ api });
    api.on("before_agent_reply", handlers.beforeAgentReply, {
      priority: 100,
      timeoutMs: WORKFLOW_HOOK_TIMEOUT_MS,
    });
    api.on("before_prompt_build", handlers.beforePromptBuild, {
      priority: 100,
      timeoutMs: PROMPT_HOOK_TIMEOUT_MS,
    });
    api.on("before_agent_run", handlers.beforeAgentRun, {
      priority: 100,
      timeoutMs: GATE_HOOK_TIMEOUT_MS,
    });
    api.on("message_received", handlers.messageReceived, {
      priority: 100,
      timeoutMs: MESSAGE_HOOK_TIMEOUT_MS,
    });
    if (typeof api?.runtime?.system?.runCommandWithTimeout === "function") {
      api.on("message_sent", handlers.messageSent, {
        priority: 100,
        timeoutMs: MESSAGE_HOOK_TIMEOUT_MS,
      });
    }
    api.on("agent_end", handlers.agentEnd, { priority: 100 });
  },
};