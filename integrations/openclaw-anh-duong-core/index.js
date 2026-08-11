import { AsyncLocalStorage } from "node:async_hooks";

import {
  WORKFLOW_ACKNOWLEDGMENT,
  createAnhDuongCoreHooks,
} from "./src/hooks.js";
import { getAsyncTaskRun } from "./src/core-client.js";
import { readCoreConfig } from "./src/config.js";

export { WORKFLOW_ACKNOWLEDGMENT } from "./src/hooks.js";

const PROMPT_HOOK_TIMEOUT_MS = 32_000;
const WORKFLOW_HOOK_TIMEOUT_MS = 65_000;
const GATE_HOOK_TIMEOUT_MS = 2_000;
const MESSAGE_HOOK_TIMEOUT_MS = 2_000;
const TELEGRAM_DELETE_TIMEOUT_MS = 10_000;
const WORKFLOW_PROGRESS_TTL_MS = 5 * 60_000;
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
  const pendingProgress = new Map();
  let config;
  try {
    config = readCoreConfig(env);
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
  }

  async function trackedFetch(url, init = {}) {
    const response = await fetchImpl(url, init);
    const call = replyContext.getStore();
    if (
      call &&
      init?.method === "POST" &&
      String(url).endsWith("/api/async-tasks") &&
      response?.ok &&
      typeof response.clone === "function"
    ) {
      try {
        const accepted = await response.clone().json();
        const payload = typeof init.body === "string" ? JSON.parse(init.body) : {};
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

  return {
    beforeAgentReply,
    beforePromptBuild: hooks.beforePromptBuild,
    beforeAgentRun: hooks.beforeAgentRun,
    messageSent,
    agentEnd: hooks.agentEnd,
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
    if (typeof api?.runtime?.system?.runCommandWithTimeout === "function") {
      api.on("message_sent", handlers.messageSent, {
        priority: 100,
        timeoutMs: MESSAGE_HOOK_TIMEOUT_MS,
      });
    }
    api.on("agent_end", handlers.agentEnd, { priority: 100 });
  },
};
