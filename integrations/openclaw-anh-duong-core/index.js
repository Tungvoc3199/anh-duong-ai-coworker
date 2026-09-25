import { AsyncLocalStorage } from "node:async_hooks";
import {
  APPROVAL_ACKNOWLEDGMENT,
  createAnhDuongCoreHooks,
  deleteTelegramWorkflowProgress,
  SAFE_MESSAGE,
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
const ORIGINAL_TURN_TTL_MS = 5 * 60_000;
const ORIGINAL_TURN_FRESH_WINDOW_MS = 30_000;
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
  realpathImpl,
  statImpl,
} = {}) {
  const replyContext = new AsyncLocalStorage();
  const pending = new Map();
  const originalTurns = new Map();
  const pendingVisualDeliveries = new Map();
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
  function originalTurnKey(sessionKey, senderId) {
    const session = typeof sessionKey === "string" ? sessionKey.trim() : "";
    const sender = typeof senderId === "string" ? senderId.trim() : "";
    return session && sender ? `${session}\0${sender}` : undefined;
  }
  function sweepOriginalTurns() {
    const current = Date.now();
    for (const [key, queue] of originalTurns) {
      const retained = queue.filter((item) => item.expiresAt > current);
      if (retained.length) originalTurns.set(key, retained); else originalTurns.delete(key);
    }
  }
  function messageReceived(event, ctx) {
    const channel = String(ctx?.channelId ?? event?.metadata?.originatingChannel ?? event?.metadata?.provider ?? "").toLowerCase();
    const text = typeof event?.content === "string" ? event.content.trim() : "";
    const key = originalTurnKey(event?.sessionKey ?? ctx?.sessionKey, event?.senderId ?? ctx?.senderId);
    if (channel !== "telegram" || !key || !text) return;
    sweepOriginalTurns();
    const isReply = event?.replyToId !== undefined || ctx?.replyToId !== undefined;
    const metadata = event?.metadata ?? {};
    const mediaPaths = isReply
      ? (Array.isArray(metadata.replyMediaPaths) && metadata.replyMediaPaths.length
          ? metadata.replyMediaPaths
          : metadata.replyMediaPath ? [metadata.replyMediaPath]
          : Array.isArray(metadata.mediaPaths) && metadata.mediaPaths.length
            ? metadata.mediaPaths
            : metadata.mediaPath ? [metadata.mediaPath] : [])
      : (Array.isArray(metadata.mediaPaths) && metadata.mediaPaths.length
          ? metadata.mediaPaths
          : metadata.mediaPath ? [metadata.mediaPath] : []);
    const mediaTypes = isReply
      ? (Array.isArray(metadata.replyMediaTypes) && metadata.replyMediaTypes.length
          ? metadata.replyMediaTypes
          : metadata.replyMediaType ? [metadata.replyMediaType]
          : Array.isArray(metadata.mediaTypes) && metadata.mediaTypes.length
            ? metadata.mediaTypes
            : metadata.mediaType ? [metadata.mediaType] : [])
      : (Array.isArray(metadata.mediaTypes) && metadata.mediaTypes.length
          ? metadata.mediaTypes
          : metadata.mediaType ? [metadata.mediaType] : []);
    const replyToId = event?.replyToId ?? ctx?.replyToId ?? metadata.replyToId;
    const replyToBody = event?.replyToBody ?? ctx?.replyToBody ?? metadata.replyToBody;
    const replyToSender = event?.replyToSender ?? ctx?.replyToSender ?? metadata.replyToSender;
    const sourceMessageId = event?.messageId ?? ctx?.messageId;
    const sourceChatId = event?.chatId ?? ctx?.chatId ?? ctx?.conversationId;
    const queue = originalTurns.get(key) ?? [];
    queue.push({
      text,
      mediaPaths,
      mediaTypes,
      replyToId,
      replyToBody,
      replyToSender,
      sourceMessageId:
        typeof sourceMessageId === "string" || typeof sourceMessageId === "number"
          ? String(sourceMessageId)
          : undefined,
      sourceChatId:
        typeof sourceChatId === "string" || typeof sourceChatId === "number"
          ? String(sourceChatId)
          : undefined,
      trustedTelegramInbound: true,
      receivedAt: Date.now(),
      expiresAt: Date.now() + ORIGINAL_TURN_TTL_MS,
    });
    originalTurns.set(key, queue.slice(-8));
  }
  function resolveOriginalTurn({ sessionKey, senderId, rawPrompt }) {
    const key = originalTurnKey(sessionKey, senderId);
    if (!key) return undefined;
    sweepOriginalTurns();
    const queue = originalTurns.get(key) ?? [];
    if (!queue.length) return undefined;
    const matching = typeof rawPrompt === "string" ? queue.filter((item) => rawPrompt.includes(item.text)) : [];
    if (matching.length === 1) return matching[0];
    if (matching.length > 1) return { ambiguous: true };
    const current = Date.now();
    const fresh = queue.filter((item) => Number.isFinite(item.receivedAt) && current >= item.receivedAt && current - item.receivedAt <= ORIGINAL_TURN_FRESH_WINDOW_MS);
    if (fresh.length === 1) return fresh[0];
    if (fresh.length > 1) return { ambiguous: true };
    return queue.length === 1 ? queue[0] : undefined;
  }
  const hooks = createAnhDuongCoreHooks({
    env,
    fetchImpl: trackedFetch,
    logger: api?.logger,
    resolveOriginalTurn,
    ...(realpathImpl === undefined ? {} : { realpathImpl }),
    ...(statImpl === undefined ? {} : { statImpl }),
    ...(workflowProgressDelayMs === undefined ? {} : { workflowProgressDelayMs }),
    loadActiveVisualReference: async (ctx) => {
      if (typeof api?.session?.state?.getSessionExtension !== "function") return undefined;
      const primarySessionKey = ctx?.runtimePolicySessionKey ?? ctx?.sessionKey ?? ctx?.sessionId;
      if (!primarySessionKey) return undefined;
      const primaryState = await api.session.state.getSessionExtension({
        sessionKey: primarySessionKey,
        namespace: "visual",
      });
      if (typeof primaryState?.activeReference === "string") return primaryState.activeReference;
      const fallbackSessionKey = ctx?.sessionKey ?? ctx?.sessionId;
      if (!fallbackSessionKey || fallbackSessionKey === primarySessionKey) return undefined;
      const fallbackState = await api.session.state.getSessionExtension({
        sessionKey: fallbackSessionKey,
        namespace: "visual",
      });
      return typeof fallbackState?.activeReference === "string"
        ? fallbackState.activeReference
        : undefined;
    },
    storeActiveVisualReference: async (ctx, activeReference) => {
      const sessionKey = ctx?.runtimePolicySessionKey ?? ctx?.sessionKey ?? ctx?.sessionId;
      if (!sessionKey || typeof api?.session?.state?.patchSessionExtension !== "function") return;
      const result = await api.session.state.patchSessionExtension({ sessionKey, namespace: "visual", value: { activeReference } });
      if (result?.ok === false) throw new Error(`native visual session state patch failed: ${result.error}`);
    },
    loadRecentAssistantReferent: async (ctx) => {
      if (typeof api?.session?.state?.getSessionExtension !== "function") return undefined;
      const primarySessionKey = ctx?.runtimePolicySessionKey ?? ctx?.sessionKey ?? ctx?.sessionId;
      if (!primarySessionKey) return undefined;
      const read = async (sessionKey) => {
        const state = await api.session.state.getSessionExtension({
          sessionKey,
          namespace: "contextual",
        });
        const candidate = state?.lastAssistantResult;
        return candidate
          && candidate.source === "previous_assistant_result"
          && typeof candidate.text === "string"
          && candidate.text.trim()
          ? candidate
          : undefined;
      };
      const primary = await read(primarySessionKey);
      if (primary) return primary;
      const fallbackSessionKey = ctx?.sessionKey ?? ctx?.sessionId;
      if (!fallbackSessionKey || fallbackSessionKey === primarySessionKey) return undefined;
      return read(fallbackSessionKey);
    },
  });
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
        return;
      }
    }
  }
  async function replyPayloadSending(event, ctx) {
    const sessionKey = event?.sessionKey ?? ctx?.sessionKey;
    const media = event?.payload?.mediaUrls?.find((item) => typeof item === "string" && item.length > 0) ?? event?.payload?.mediaUrl;
    if (sessionKey && typeof media === "string" && media.length > 0) {
      const queue = pendingVisualDeliveries.get(sessionKey) ?? [];
      queue.push(media);
      pendingVisualDeliveries.set(sessionKey, queue);
    }
    return undefined;
  }
  async function messageSent(event, ctx) {
    const message = normalizeMessageSent(event, ctx);
    if (
      message.channelId === "telegram"
      && message.sessionKey
      && message.success === true
      && message.messageId !== undefined
      && message.messageId !== null
      && typeof message.content === "string"
    ) {
      const content = message.content.trim();
      if (
        content
        && content !== WORKFLOW_ACKNOWLEDGMENT
        && content !== APPROVAL_ACKNOWLEDGMENT
        && content !== SAFE_MESSAGE
        && typeof api?.session?.state?.patchSessionExtension === "function"
      ) {
        const result = await api.session.state.patchSessionExtension({
          sessionKey: message.sessionKey,
          namespace: "contextual",
          value: {
            lastAssistantResult: {
              source: "previous_assistant_result",
              message_id: String(message.messageId),
              text: content.slice(0, 12_000),
              sender: "Ánh Dương",
            },
          },
        });
        if (result?.ok === false) {
          throw new Error("native contextual session state patch failed: " + result.error);
        }
      }
    }
    if (message.sessionKey) {
      const queue = pendingVisualDeliveries.get(message.sessionKey);
      const candidate = queue?.shift();
      if (queue?.length) pendingVisualDeliveries.set(message.sessionKey, queue); else pendingVisualDeliveries.delete(message.sessionKey);
      if (candidate && message.success === true && typeof api?.session?.state?.patchSessionExtension === "function") {
        const result = await api.session.state.patchSessionExtension({ sessionKey: message.sessionKey, namespace: "visual", value: { activeReference: candidate } });
        if (result?.ok === false) throw new Error(`native visual session state patch failed: ${result.error}`);
      }
    }
    if (message.channelId !== "telegram" || message.content !== WORKFLOW_ACKNOWLEDGMENT || message.success === false || message.messageId === undefined || message.messageId === null) return undefined;
    const progress = take(event, ctx); if (!progress) return undefined;
    scheduleWorkflowCleanup(monitor(progress, String(message.messageId))); return undefined;
  }
  return { messageReceived, beforeAgentReply: trackedReply, beforePromptBuild: hooks.beforePromptBuild, beforeAgentRun: hooks.beforeAgentRun, beforeToolCall: hooks.beforeToolCall, replyPayloadSending, messageSent, agentEnd: hooks.agentEnd };
}

export function createPluginHandlersLegacy(options) { return createPluginHandlers(options); }

export default {
  id: "anh-duong-core", name: "Ánh Dương Core Gate", description: "Fail-closed Core preparation gate for ordinary Telegram agent turns.",
  register(api) {
    api.session.state.registerSessionExtension({ namespace: "visual", description: "Ánh Dương active visual reference" });
    api.session.state.registerSessionExtension({ namespace: "contextual", description: "Ánh Dương previous assistant referent" });
    const handlers = createPluginHandlers({ api });
    api.on("message_received", handlers.messageReceived, { priority: 100, timeoutMs: MESSAGE_HOOK_TIMEOUT_MS });
    api.on("before_agent_reply", handlers.beforeAgentReply, { priority: 100, timeoutMs: WORKFLOW_HOOK_TIMEOUT_MS });
    api.on("before_prompt_build", handlers.beforePromptBuild, { priority: 100, timeoutMs: PROMPT_HOOK_TIMEOUT_MS });
    api.on("before_agent_run", handlers.beforeAgentRun, { priority: 100, timeoutMs: GATE_HOOK_TIMEOUT_MS });
    api.on("before_tool_call", handlers.beforeToolCall, { priority: 100, timeoutMs: GATE_HOOK_TIMEOUT_MS });
    api.on("reply_payload_sending", handlers.replyPayloadSending, { priority: 100, timeoutMs: MESSAGE_HOOK_TIMEOUT_MS });
    api.on("message_sent", handlers.messageSent, { priority: 100, timeoutMs: MESSAGE_HOOK_TIMEOUT_MS });
    api.on("agent_end", handlers.agentEnd, { priority: 100 });
  },
};
