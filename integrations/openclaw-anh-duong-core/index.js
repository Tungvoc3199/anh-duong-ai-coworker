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
const MESSAGE_HOOK_TIMEOUT_MS = 20_000;
const WORKFLOW_PROGRESS_TTL_MS = 5 * 60_000;
const ORIGINAL_TURN_TTL_MS = 5 * 60_000;
const ORIGINAL_TURN_FRESH_WINDOW_MS = 30_000;
const DEFAULT_POLL_MS = 2_000;
const TELEGRAM_API_TIMEOUT_MS = 8_000;
const TELEGRAM_CLI_TIMEOUT_MS = 35_000;
const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "blocked", "cancelled"]);

function safeLog(logger, level, fields) {
  try { logger?.[level]?.(JSON.stringify(fields)); } catch { /* cleanup is best effort */ }
}

const PRESENCE_THINKING = "🧠 Đang kết ý thành lời…";
const ASYNC_SESSION_PREFIX = "anh-duong-async:";
const ASYNC_TASK_SESSION_MARKER = "openresponses-user:async:";

function coreTaskIdFromSessionKey(sessionKey) {
  const value = typeof sessionKey === "string" ? sessionKey.trim() : "";
  const markerIndex = value.lastIndexOf(ASYNC_TASK_SESSION_MARKER);
  if (markerIndex < 0) return undefined;
  if (markerIndex > 0 && value[markerIndex - 1] !== ":") return undefined;
  const taskId = value.slice(markerIndex + ASYNC_TASK_SESSION_MARKER.length).trim();
  return /^task_[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(taskId) ? taskId : undefined;
}

function coreRunIdFromSessionKey(sessionKey) {
  const value = typeof sessionKey === "string" ? sessionKey.trim() : "";
  const markerIndex = value.lastIndexOf(ASYNC_SESSION_PREFIX);
  if (markerIndex < 0) return undefined;
  if (markerIndex > 0 && value[markerIndex - 1] !== ":") return undefined;
  const runId = value.slice(markerIndex + ASYNC_SESSION_PREFIX.length).trim();
  return /^run_[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(runId) ? runId : undefined;
}

function safeToolText(value, max = 72) {
  if (typeof value !== "string") return "";
  return value.replace(/\s+/g, " ").trim().slice(0, max);
}

function safeUrlHost(value) {
  try { return new URL(String(value)).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function toolActivityLabel(event) {
  const rawName = safeToolText(event?.toolName ?? event?.name ?? event?.tool?.name, 48);
  const name = rawName.toLowerCase();
  const params = event?.params ?? event?.arguments ?? event?.input ?? {};
  if (name.includes("search")) {
    const query = safeToolText(params?.query ?? params?.q);
    return query ? `🔎 ${rawName || "search"} · “${query}”` : `🔎 ${rawName || "search"}`;
  }
  if (name.includes("web") || name.includes("browser") || name.includes("fetch") || name.includes("read")) {
    const host = safeUrlHost(params?.url ?? params?.uri);
    return host ? `🌐 ${rawName || "web_read"} · ${host}` : `🌐 ${rawName || "web_read"}`;
  }
  if (name.includes("image") || name.includes("visual")) return `🎨 ${rawName || "image"}`;
  if (name.includes("memory")) return `🧠 ${rawName || "memory"}`;
  if (name.includes("message") || name.includes("send")) return `✉️ ${rawName || "message"}`;
  return `🛠️ ${rawName || "tool"}`;
}

function normalizeTelegramTarget(value) {
  if (value === undefined || value === null) return undefined;
  const text = String(value).trim().replace(/^telegram:/i, "");
  return text || undefined;
}

async function runTelegramMessageCommand(api, args) {
  const runner = api?.runtime?.system?.runCommandWithTimeout;
  if (typeof runner !== "function") return undefined;
  const result = await runner(
    [process.execPath, "/app/openclaw.mjs", "message", ...args, "--json"],
    { timeoutMs: TELEGRAM_CLI_TIMEOUT_MS, cwd: "/app" },
  );
  if (result?.code !== 0) return undefined;
  try { return JSON.parse(result?.stdout ?? ""); } catch { return undefined; }
}

function platformMessageId(payload) {
  const candidates = [payload?.payload?.messageId, payload?.payload?.message_id, payload?.payload?.primaryPlatformMessageId, payload?.messageId, payload?.message_id, payload?.receipt?.primaryPlatformMessageId];
  const value = candidates.find((item) => item !== undefined && item !== null);
  return value === undefined ? undefined : String(value);
}

function telegramBotToken(api) {
  const raw = api?.config?.channels?.telegram?.botToken;
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  const envName = api?.config?.channels?.telegram?.tokenEnv;
  if (typeof envName === "string" && envName.trim()) {
    const token = process.env[envName.trim()];
    if (typeof token === "string" && token.trim()) return token.trim();
  }
  return undefined;
}

async function telegramApi(api, method, body) {
  const token = telegramBotToken(api);
  if (!token) return undefined;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TELEGRAM_API_TIMEOUT_MS);
  try {
    const response = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(body), signal: controller.signal,
    });
    if (!response.ok) return undefined;
    return await response.json();
  } finally { clearTimeout(timer); }
}

async function reactToInbound(api, chatId, messageId) {
  const target = normalizeTelegramTarget(chatId);
  if (!target || messageId === undefined || messageId === null) return;
  const direct = await telegramApi(api, "setMessageReaction", {
    chat_id: target, message_id: Number(messageId),
    reaction: [{ type: "emoji", emoji: "👀" }],
  });
  if (!direct?.ok) await runTelegramMessageCommand(api, ["react", "--channel", "telegram", "--target", target, "--message-id", String(messageId), "--emoji", "👀"]);
}

async function sendPresence(api, chatId, text) {
  const target = normalizeTelegramTarget(chatId);
  if (!target) return undefined;
  const direct = await telegramApi(api, "sendMessage", {
    chat_id: target, text, disable_notification: true,
  });
  const directId = direct?.result?.message_id;
  if (directId !== undefined && directId !== null) return String(directId);
  const payload = await runTelegramMessageCommand(api, ["send", "--channel", "telegram", "--target", target, "--message", text, "--silent"]);
  return platformMessageId(payload);
}

async function editPresence(api, chatId, messageId, text) {
  const target = normalizeTelegramTarget(chatId);
  if (!target || !messageId) return;
  const direct = await telegramApi(api, "editMessageText", {
    chat_id: target, message_id: Number(messageId), text,
  });
  if (direct?.ok) return;
  await runTelegramMessageCommand(api, ["edit", "--channel", "telegram", "--target", target, "--message-id", String(messageId), "--message", text]);
}

async function deletePresence(api, { chatId, messageId }) {
  const target = normalizeTelegramTarget(chatId);
  if (!target || !messageId) return;
  const direct = await telegramApi(api, "deleteMessage", {
    chat_id: target, message_id: Number(messageId),
  });
  if (direct?.ok) return;
  await deleteTelegramWorkflowProgress(api, { chatId: target, messageId });
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
  deleteWorkflowProgress = (target) => deletePresence(api, target),
  scheduleWorkflowCleanup = (task) => { void task; },
  realpathImpl,
  statImpl,
} = {}) {
  const replyContext = new AsyncLocalStorage();
  const pending = new Map();
  const originalTurns = new Map();
  const pendingVisualDeliveries = new Map();
  const telegramTargets = new Map();
  const workflowGateBypass = new Set();
  const presence = new Map();
  const presenceBySession = new Map();
  const presenceByRun = new Map();
  const presenceByTask = new Map();
  const acceptedByPresence = new Map();
  const cleanupScheduledRuns = new Set();
  let config;
  try { config = readCoreConfig(env); } catch { config = undefined; }

  function resolvePresenceKey({ sessionKey, chatId } = {}) {
    const directKey = progressKey(sessionKey, chatId);
    if (directKey && presence.has(directKey)) return directKey;
    if (typeof sessionKey === "string") {
      const sessionMatch = presenceBySession.get(sessionKey);
      if (sessionMatch && presence.has(sessionMatch)) return sessionMatch;
      const mappedKey = progressKey(undefined, telegramTargets.get(sessionKey));
      if (mappedKey && presence.has(mappedKey)) return mappedKey;
    }
    return undefined;
  }

  function clearPresenceBindings(pKey) {
    if (!pKey) return;
    for (const [sessionKey, boundKey] of presenceBySession) {
      if (boundKey === pKey) presenceBySession.delete(sessionKey);
    }
    for (const [runId, boundKey] of presenceByRun) {
      if (boundKey === pKey) presenceByRun.delete(runId);
    }
    for (const [taskId, boundKey] of presenceByTask) {
      if (boundKey === pKey) presenceByTask.delete(taskId);
    }
    acceptedByPresence.delete(pKey);
  }

  function bindTaskPresence(taskId, pKey) {
    if (typeof taskId === "string" && pKey && presence.has(pKey)) {
      presenceByTask.set(taskId, pKey);
    }
  }

  function bindRunPresence(runId, pKey) {
    if (typeof runId === "string" && pKey && presence.has(pKey)) {
      presenceByRun.set(runId, pKey);
    }
  }

  function scheduleRunCleanup(accepted, pKey) {
    if (!accepted?.runId || !pKey || cleanupScheduledRuns.has(accepted.runId)) return;
    const item = presence.get(pKey);
    if (!item) return;
    cleanupScheduledRuns.add(accepted.runId);
    scheduleWorkflowCleanup(monitor({ ...accepted, chatId: item.chatId, pKey }, String(item.messageId)));
  }

  async function trackedFetch(url, init = {}) {
    const call = replyContext.getStore();
    const response = await fetchImpl(url, init);
    if (String(url).endsWith("/api/async-tasks") && response?.ok) {
      try {
        const accepted = await response.clone().json();
        const payload = typeof init.body === "string" ? JSON.parse(init.body) : {};
        if (typeof accepted?.run_id === "string" && typeof accepted?.task_id === "string") {
          const acceptedBinding = {
            runId: accepted.run_id,
            taskId: accepted.task_id,
            requestId: payload.correlation_id,
            replayed: accepted.replayed === true,
            status: accepted.status,
          };
          const payloadPresenceKey = resolvePresenceKey({
            sessionKey: payload.source_session_id,
            chatId: payload.source_chat_id,
          });
          const boundKey = payloadPresenceKey ?? call?.presenceKey;
          if (boundKey) {
            bindRunPresence(acceptedBinding.runId, boundKey);
            bindTaskPresence(acceptedBinding.taskId, boundKey);
            acceptedByPresence.set(boundKey, acceptedBinding);
            safeLog(api?.logger, "info", {
              event: "anh_duong_presence_async_bind",
              outcome: "bound",
              has_task_id: true,
              has_run_id: true,
              source: payloadPresenceKey ? "async_payload" : "reply_context",
            });
          }
          if (call) call.accepted = acceptedBinding;
        }
      } catch {
        safeLog(api?.logger, "warn", { event: "anh_duong_presence_async_bind", outcome: "best_effort_failure" });
      }
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
  async function messageReceived(event, ctx) {
    const channel = String(ctx?.channelId ?? event?.metadata?.originatingChannel ?? event?.metadata?.provider ?? "").toLowerCase();
    const text = typeof event?.content === "string" ? event.content.trim() : "";
    const key = originalTurnKey(event?.sessionKey ?? ctx?.sessionKey, event?.senderId ?? ctx?.senderId);
    if (channel !== "telegram" || !key || !text) return;

    // Capture trusted inbound context before the first await. Presence transport is
    // best-effort and must never race original-turn/reply/visual state persistence.
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

    const inboundChatId = sourceChatId;
    const turnSessionKey = ctx?.sessionKey ?? event?.sessionKey;
    telegramTargets.set(turnSessionKey, inboundChatId);
    const inboundMessageId = sourceMessageId;
    const pKey = progressKey(turnSessionKey, inboundChatId);
    const startedAt = Date.now();
    if (pKey && !presence.has(pKey)) {
      try {
        const presenceMessageId = await sendPresence(api, inboundChatId, PRESENCE_THINKING);
        if (presenceMessageId) {
          presence.set(pKey, { chatId: inboundChatId, messageId: presenceMessageId, toolCount: 0, startedAt, phase: "thinking" });
          if (typeof turnSessionKey === "string" && turnSessionKey) {
            presenceBySession.set(turnSessionKey, pKey);
          }
        }
        safeLog(api?.logger, "info", { event: "anh_duong_presence_start", outcome: presenceMessageId ? "sent" : "no_message_id", has_chat_id: Boolean(inboundChatId), channel });
      } catch {
        safeLog(api?.logger, "warn", { event: "anh_duong_presence_start", outcome: "best_effort_failure" });
      }
    }
    const reactionTask = reactToInbound(api, inboundChatId, inboundMessageId).catch(() => {
      safeLog(api?.logger, "warn", { event: "anh_duong_presence_reaction", outcome: "best_effort_failure" });
    });
    await Promise.allSettled([reactionTask]);
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
    const key = progressKey(ctx?.sessionKey, ctx?.chatId ?? telegramTargets.get(ctx?.sessionKey)); if (!key) return;
    sweep(); const queue = pending.get(key) ?? [];
    queue.push({ ...accepted, chatId: ctx?.chatId ?? telegramTargets.get(ctx?.sessionKey), sessionKey: ctx?.sessionKey, expiresAt: Date.now() + WORKFLOW_PROGRESS_TTL_MS });
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
    const sessionKey = ctx?.sessionKey ?? event?.sessionKey;
    const chatId = ctx?.chatId ?? ctx?.conversationId ?? event?.chatId ?? telegramTargets.get(sessionKey);
    const pKey = resolvePresenceKey({ sessionKey, chatId }) ?? progressKey(sessionKey, chatId);
    const call = { presenceKey: pKey, sessionKey, chatId };
    const result = await replyContext.run(call, () => hooks.beforeAgentReply(event, ctx));
    const channel = String(ctx?.channelId ?? ctx?.channel ?? ctx?.messageProvider ?? "").toLowerCase();
    if (result?.reply?.text === WORKFLOW_ACKNOWLEDGMENT && ctx?.runId) workflowGateBypass.add(ctx.runId);
    if (channel === "telegram" && pKey && (result === undefined || result?.reply?.text === WORKFLOW_ACKNOWLEDGMENT) && !presence.has(pKey)) {
      try {
        const messageId = await sendPresence(api, chatId, PRESENCE_THINKING);
        if (messageId) {
          presence.set(pKey, { chatId, messageId, toolCount: 0, startedAt: Date.now(), phase: "thinking" });
          if (typeof sessionKey === "string" && sessionKey) presenceBySession.set(sessionKey, pKey);
        }
        safeLog(api?.logger, "info", { event: "anh_duong_presence_start", outcome: messageId ? "sent" : "no_message_id", has_chat_id: Boolean(chatId), channel });
      } catch {
        safeLog(api?.logger, "warn", { event: "anh_duong_presence_start", outcome: "best_effort_failure" });
      }
    }
    const accepted = (pKey ? acceptedByPresence.get(pKey) : undefined) ?? call.accepted;
    if (accepted && pKey) {
      bindRunPresence(accepted.runId, pKey);
      if (accepted.taskId) bindTaskPresence(accepted.taskId, pKey);
      scheduleRunCleanup(accepted, pKey);
    }
    if (result?.reply?.text === WORKFLOW_ACKNOWLEDGMENT) {
      if (accepted) remember(ctx, accepted);
      // Never emit the legacy workflow ACK. One transient presence message owns workflow progress.
      return { ...result, reply: undefined, reason: "anh_duong_workflow_native_progress" };
    }
    if (result?.reason === "anh_duong_workflow_completed_before_progress" && accepted) {
      remember(ctx, accepted);
      const item = pKey ? presence.get(pKey) : undefined;
      if (item) {
        return { ...result, reply: undefined, reason: "anh_duong_workflow_presence_active" };
      }
      safeLog(api?.logger, "warn", { event: "anh_duong_workflow_native_progress", outcome: "terminal_before_progress" });
      return { ...result, reply: undefined, reason: "anh_duong_workflow_native_progress" };
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
        try {
          await deleteWorkflowProgress({ chatId: progress.chatId, messageId });
          if (progress.pKey) {
            presence.delete(progress.pKey);
            clearPresenceBindings(progress.pKey);
          }
          cleanupScheduledRuns.delete(progress.runId);
          safeLog(api?.logger, "info", { event: "anh_duong_core_workflow_progress_cleanup", outcome: "deleted", request_id: progress.requestId });
          return;
        } catch {
          safeLog(api?.logger, "warn", { event: "anh_duong_core_workflow_progress_cleanup", outcome: "retry_delete", request_id: progress.requestId });
        }
      }
    }
    cleanupScheduledRuns.delete(progress.runId);
    safeLog(api?.logger, "warn", { event: "anh_duong_core_workflow_progress_cleanup", outcome: "exhausted", request_id: progress.requestId });
  }
  async function trackedToolCall(event, ctx) {
    const decision = await hooks.beforeToolCall(event, ctx);
    if (decision?.block === true) return decision;
    const chatId = ctx?.chatId ?? telegramTargets.get(ctx?.sessionKey);
    const asyncTaskId = coreTaskIdFromSessionKey(ctx?.sessionKey);
    const asyncRunId = coreRunIdFromSessionKey(ctx?.sessionKey);
    const directKey = resolvePresenceKey({ sessionKey: ctx?.sessionKey, chatId });
    const pKey = directKey
      ?? (asyncTaskId ? presenceByTask.get(asyncTaskId) : undefined)
      ?? (asyncRunId ? presenceByRun.get(asyncRunId) : undefined);
    const item = pKey ? presence.get(pKey) : undefined;
    if (item) {
      item.toolCount += 1;
      const activity = toolActivityLabel(event);
      if (item.lastActivity !== activity) {
        item.phase = "tool";
        item.lastActivity = activity;
        try {
          await editPresence(api, item.chatId, item.messageId, activity);
          safeLog(api?.logger, "info", { event: "anh_duong_presence_tool", outcome: "updated", tool: String(event?.toolName ?? event?.name ?? event?.tool?.name ?? "unknown"), tool_count: item.toolCount });
        } catch {
          safeLog(api?.logger, "warn", { event: "anh_duong_presence_tool", outcome: "best_effort_failure" });
        }
      }
    }
    return decision;
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
    const pKey = resolvePresenceKey({ sessionKey: message.sessionKey, chatId: message.to });
    const activePresence = pKey ? presence.get(pKey) : undefined;
    const isPresenceMessage = message.content === PRESENCE_THINKING
      || message.content === "⚙️ Đang thực thi…"
      || (typeof message.content === "string" && /^(🔎|🌐|🎨|🧠|✉️|🛠️) /.test(message.content));
    const isFinalVisibleMessage = message.channelId === "telegram"
      && message.success === true
      && typeof message.content === "string"
      && !isPresenceMessage
      && message.content !== WORKFLOW_ACKNOWLEDGMENT
      && message.content !== APPROVAL_ACKNOWLEDGMENT;
    if (activePresence && isFinalVisibleMessage) {
      try {
        await deleteWorkflowProgress({ chatId: activePresence.chatId, messageId: activePresence.messageId });
        presence.delete(pKey);
        clearPresenceBindings(pKey);
        safeLog(api?.logger, "info", { event: "anh_duong_presence_finish", outcome: "deleted" });
      } catch {
        safeLog(api?.logger, "warn", { event: "anh_duong_presence_finish", outcome: "best_effort_failure" });
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
  async function trackedBeforeAgentRun(event, ctx) { if (ctx?.runId && workflowGateBypass.delete(ctx.runId)) return { outcome: 'pass' }; return hooks.beforeAgentRun(event, ctx); }
  return { messageReceived, beforeAgentReply: trackedReply, beforePromptBuild: hooks.beforePromptBuild, beforeAgentRun: trackedBeforeAgentRun, beforeToolCall: trackedToolCall, replyPayloadSending, messageSent, agentEnd: hooks.agentEnd };
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
