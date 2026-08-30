import { AsyncLocalStorage } from "node:async_hooks";
import {
  createAnhDuongCoreHooks,
  deleteTelegramWorkflowProgress,
  WORKFLOW_ACKNOWLEDGMENT,
} from "./src/hooks.js";
import { getAsyncTaskRun } from "./src/core-client.js";
import { readCoreConfig } from "./src/config.js";

export { WORKFLOW_ACKNOWLEDGMENT, deleteTelegramWorkflowProgress };

const PROMPT_HOOK_TIMEOUT_MS = 32_000;
const WORKFLOW_HOOK_TIMEOUT_MS = 65_000;
const GATE_HOOK_TIMEOUT_MS = 2_000;
const MESSAGE_HOOK_TIMEOUT_MS = 2_000;
const WORKFLOW_PROGRESS_TTL_MS = 5 * 60_000;
const DEFAULT_POLL_MS = 2_000;
const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "blocked", "cancelled"]);

function safeLog(logger, level, fields) {
  try { logger?.[level]?.(JSON.stringify(fields)); } catch { /* cleanup is best effort */ }
}

function progressKey(sessionKey, chatId) {
  if (chatId !== undefined && chatId !== null && String(chatId).length > 0) return `chat:${chatId}`;
  if (typeof sessionKey === "string" && sessionKey.length > 0) return `session:${sessionKey}`;
  return undefined;
}

function normalizeMessageSent(event, ctx) {
  return {
    channelId: ctx?.channelId ?? ctx?.channel ?? event?.channelId ?? event?.channel,
    content: event?.content ?? event?.text,
    success: event?.success ?? event?.ok,
    messageId: event?.messageId ?? event?.receipt?.primaryPlatformMessageId,
    sessionKey: event?.sessionKey ?? ctx?.sessionKey,
    to: event?.to ?? event?.chatId ?? ctx?.conversationId,
  };
}

export function createPluginHandlers({
  api,
  env = process.env,
  fetchImpl = fetch,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  workflowProgressDelayMs,
  workflowProgressCleanupPollMs = DEFAULT_POLL_MS,
  workflowProgressCleanupMaxAttempts = 900,
  deleteWorkflowProgress = (target) => deleteTelegramWorkflowProgress(api, target),
  scheduleWorkflowCleanup = (task) => { void task; },
} = {}) {
  const replyContext = new AsyncLocalStorage();
  const pending = new Map();
  let lastAccepted;
  let config;
  try { config = readCoreConfig(env); } catch { config = undefined; }
  async function trackedFetch(url, init = {}) {
    const call = replyContext.getStore();
    const response = await fetchImpl(url, init);
    if (call && String(url).endsWith("/api/async-tasks") && response?.ok) {
      try {
        const accepted = await response.clone().json();
        const payload = typeof init.body === "string" ? JSON.parse(init.body) : {};
        if (typeof accepted?.run_id === "string" && accepted.replayed !== true && accepted.status !== "blocked") {
          call.accepted = { runId: accepted.run_id, requestId: payload.correlation_id };
          lastAccepted = call.accepted;
        }
      } catch { /* Core response validation remains authoritative. */ }
    }
    return response;
  }
  const hooks = createAnhDuongCoreHooks({ env, fetchImpl: trackedFetch, logger: api?.logger, ...(workflowProgressDelayMs === undefined ? {} : { workflowProgressDelayMs }) });
  function sweep() {
    const now = Date.now();
    for (const [key, queue] of pending) {
      const retained = queue.filter((item) => item.expiresAt > now);
      if (retained.length) pending.set(key, retained); else pending.delete(key);
    }
  }
  function remember(ctx, accepted) {
    const key = progressKey(ctx?.sessionKey, ctx?.chatId); if (!key) return;
    sweep(); const queue = pending.get(key) ?? [];
    queue.push({ ...accepted, chatId: ctx?.chatId, sessionKey: ctx?.sessionKey, expiresAt: Date.now() + WORKFLOW_PROGRESS_TTL_MS });
    pending.set(key, queue);
  }
  function take(event, ctx) {
    sweep();
    const message = normalizeMessageSent(event, ctx);
    const keys = [progressKey(undefined, message.to), progressKey(message.sessionKey, undefined)].filter(Boolean);
    for (const key of new Set(keys)) {
      const queue = pending.get(key); if (!queue?.length) continue;
      const item = queue.shift(); if (queue.length) pending.set(key, queue); else pending.delete(key);
      if (item.chatId === undefined) item.chatId = message.to;
      return item;
    }
    return undefined;
  }
  async function trackedReply(event, ctx) {
    const call = {};
    const result = await replyContext.run(call, () => hooks.beforeAgentReply(event, ctx));
    const accepted = call.accepted ?? lastAccepted;
    if (result?.reply?.text === WORKFLOW_ACKNOWLEDGMENT && accepted) remember(ctx, accepted);
    if (result?.reason === "anh_duong_workflow_completed_before_progress" && accepted) {
      remember(ctx, accepted);
      return { ...result, reply: { text: WORKFLOW_ACKNOWLEDGMENT }, reason: "anh_duong_workflow_progress_after_threshold" };
    }
    return result;
  }
  async function monitor(progress, messageId) {
    if (!config?.enabled) return;
    const attempts = Math.max(1, Math.floor(Number(workflowProgressCleanupMaxAttempts) || 1));
    const poll = Math.max(0, Number(workflowProgressCleanupPollMs) || 0);
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      if (attempt && poll) await sleep(poll);
      let run; try { run = await getAsyncTaskRun({ config, runId: progress.runId, requestId: progress.requestId, fetchImpl }); } catch { continue; }
      if (!TERMINAL_RUN_STATUSES.has(run.status)) continue;
      if (run.notification_status === "sent") {
        try { await deleteWorkflowProgress({ chatId: progress.chatId, messageId }); safeLog(api?.logger, "info", { event: "anh_duong_core_workflow_progress_cleanup", outcome: "deleted", request_id: progress.requestId }); }
        catch { safeLog(api?.logger, "warn", { event: "anh_duong_core_workflow_progress_cleanup", outcome: "failure", request_id: progress.requestId }); }
      }
      return;
    }
  }
  async function messageSent(event, ctx) {
    const message = normalizeMessageSent(event, ctx);
    if (message.channelId !== "telegram" || message.content !== WORKFLOW_ACKNOWLEDGMENT || message.success === false || message.messageId === undefined || message.messageId === null) return undefined;
    const progress = take(event, ctx); if (!progress) return undefined;
    scheduleWorkflowCleanup(monitor(progress, String(message.messageId))); return undefined;
  }
  return { beforeAgentReply: trackedReply, beforePromptBuild: hooks.beforePromptBuild, beforeAgentRun: hooks.beforeAgentRun, beforeToolCall: hooks.beforeToolCall, messageSent, agentEnd: hooks.agentEnd };
}

export function createPluginHandlersLegacy(options) { return createPluginHandlers(options); }

export default {
  id: "anh-duong-core", name: "Ánh Dương Core Gate", description: "Fail-closed Core preparation gate for ordinary Telegram agent turns.",
  register(api) {
    const handlers = createPluginHandlers({ api });
    api.on("before_agent_reply", handlers.beforeAgentReply, { priority: 100, timeoutMs: WORKFLOW_HOOK_TIMEOUT_MS });
    api.on("before_prompt_build", handlers.beforePromptBuild, { priority: 100, timeoutMs: PROMPT_HOOK_TIMEOUT_MS });
    api.on("before_agent_run", handlers.beforeAgentRun, { priority: 100, timeoutMs: GATE_HOOK_TIMEOUT_MS });
    api.on("before_tool_call", handlers.beforeToolCall, { priority: 100, timeoutMs: GATE_HOOK_TIMEOUT_MS });
    if (typeof api?.runtime?.system?.runCommandWithTimeout === "function") api.on("message_sent", handlers.messageSent, { priority: 100, timeoutMs: MESSAGE_HOOK_TIMEOUT_MS });
    api.on("agent_end", handlers.agentEnd, { priority: 100 });
  },
};
