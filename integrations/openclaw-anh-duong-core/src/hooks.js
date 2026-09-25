import { createHash } from "node:crypto";
import { realpathSync, statSync } from "node:fs";
import { posix as posixPath } from "node:path";
import { CoreIntegrationError, readCoreConfig } from "./config.js";
import {
  buildAsyncTaskCreate,
  getAsyncTaskRun,
  buildCoreRequest,
  parseApprovalContinuation,
  parseApprovalIntent,
  prepareCoreRequest,
  resolveApproval,
  resolveLatestApproval,
  submitAsyncTask,
} from "./core-client.js";
import { buildPreparedContext } from "./prompt.js";

export const SAFE_MESSAGE =
  "Ánh Dương Core hiện chưa sẵn sàng xử lý yêu cầu này. Vui lòng thử lại sau.";

export const WORKFLOW_ACKNOWLEDGMENT =
  "Em đã nhận việc và đang xử lý. Em sẽ báo lại ngay khi hoàn tất.";

export const APPROVAL_ACKNOWLEDGMENT =
  "Em đã nhận duyệt và tiếp tục đúng tác vụ đang chờ.";

function appendCapabilityPolicy(prepared, preparedContext) {
  const route = prepared?.route_decision?.route;
  const capability = prepared?.capability_decision?.capability;
  if (capability === "visual_analysis") {
    const operation = prepared?.visual_interaction?.operation;
    if (operation === "search") {
      return `${preparedContext}\ntool_policy: visual_search_read_only\nallowed_tools: web_search, web_fetch\nevidence_policy: Use only public read-only web evidence. Do not create or edit images, write files, send messages, publish, or mutate runtime state.`;
    }
    return `${preparedContext}\ntool_policy: no_tools\nevidence_policy: Analyze only the visual evidence described by Core. Do not call tools, create or edit images, send photos, or claim unavailable pixels were inspected.`;
  }
  if (route === "direct") {
    return `${preparedContext}\ntool_policy: no_tools\nevidence_policy: Do not call tools. If any tool attempt is blocked, do not claim that a tool was executed, checked, searched, read, or verified.`;
  }
  if (route === "core_read") {
    return `${preparedContext}\ntool_policy: no_tools\nevidence_policy: Answer only from the prepared current Core context. Do not call tools or claim evidence outside that context.`;
  }
  if (route === "web_read") {
    return `${preparedContext}\ntool_policy: web_read_tools_only\nallowed_tools: web_search, web_fetch, x_search\nevidence_policy: Use only public read-only web evidence. Do not call browser, messaging, runtime, file-write, or mutation tools.`;
  }
  if (route === "memory") {
    return `${preparedContext}\ntool_policy: memory_tools_only\nallowed_tools: memory_search, memory_get\nevidence_policy: Use memory tool results as historical memory evidence. Do not present historical operational facts as current runtime truth unless current Core context explicitly verifies them.`;
  }
  return preparedContext;
}
export async function deleteTelegramWorkflowProgress(api, { chatId, messageId }) {
  const runner = api?.runtime?.system?.runCommandWithTimeout;
  if (typeof runner !== "function") {
    throw new Error("OpenClaw runtime command helper is unavailable.");
  }
  const target = normalizeTelegramChatTarget(chatId);
  if (!target) {
    throw new Error("OpenClaw Telegram progress deletion target is invalid.");
  }
  const result = await runner([
    process.execPath, "/app/openclaw.mjs", "message", "delete",
    "--channel", "telegram", "--target", target,
    "--message-id", String(messageId), "--json",
  ], { timeoutMs: 30_000, cwd: "/app" });
  if (result?.code !== 0) {
    throw new Error("OpenClaw Telegram progress deletion failed.");
  }
  let payload;
  try {
    payload = JSON.parse(result?.stdout ?? "")?.payload;
  } catch {
    throw new Error("OpenClaw Telegram progress deletion returned invalid JSON.");
  }
  if (payload?.deleted === true || payload?.ok === true) {
    return;
  }
  const warning = typeof payload?.warning === "string" ? payload.warning.toLowerCase() : "";
  if (warning.includes("message to delete not found")) {
    return;
  }
  throw new Error("OpenClaw Telegram progress deletion was not confirmed.");
}
const STATE_TTL_MS = 5 * 60 * 1_000;
const RECENT_VISUAL_TTL_MS = 6 * 60 * 60 * 1_000;
const WORKFLOW_PROGRESS_DELAY_MS = 1_500;
const TERMINAL_RUN_STATUSES = new Set([
  "completed",
  "failed",
  "blocked",
  "cancelled",
]);

function managedChannel(ctx) {
  const channel = ctx?.messageProvider ?? ctx?.channel;
  return channel === "telegram" || channel === "zalouser" ? channel : undefined;
}

function isTelegram(ctx) {
  return managedChannel(ctx) === "telegram";
}

function isManagedChannel(ctx) {
  return managedChannel(ctx) !== undefined;
}

function normalizeTelegramChatTarget(value) {
  if (typeof value !== "string" && typeof value !== "number") return undefined;
  const text = String(value).trim();
  if (!text) return undefined;
  const normalized = text.replace(/^telegram:/i, "");
  return normalized.length > 0 ? normalized : undefined;
}

function resolveTurnRunId(ctx, prompt, currentTime) {
  const runId = ctx?.runId;
  if (typeof runId === "string" && runId.length > 0) {
    return runId;
  }
  const sessionId =
    typeof ctx?.sessionId === "string" && ctx.sessionId.length > 0
      ? ctx.sessionId
      : ctx?.sessionKey;
  if (
    typeof sessionId !== "string" ||
    sessionId.length === 0 ||
    typeof prompt !== "string" ||
    prompt.length === 0
  ) {
    return undefined;
  }
  const bucket = Math.floor(currentTime / STATE_TTL_MS);
  const digest = createHash("sha256").update(`${sessionId}\0${prompt}\0${bucket}`).digest("hex");
  return `compat-${digest}`;
}

// Runtime-emitted retry continuations that the harness APPENDS to the original
// prompt when an attempt produced no user-visible answer. These are synthetic
// control instructions, never user intent, so they must not be re-classified.
const RETRY_CONTINUATION_MARKERS = [
  "did not produce a user-visible answer",
  "Do not restart from scratch",
  "produce the visible answer now",
];

/**
 * Detects a synthetic retry continuation and recovers the original user intent.
 *
 * The harness builds the retry prompt as `${basePrompt}\n\n${instruction}`, so
 * the original request is preserved as a prefix. We split on that boundary and
 * return the untouched user text, which keeps the Core classification stable
 * across retries instead of re-routing an imperative control string.
 */
function splitRetryContinuation(prompt) {
  if (typeof prompt !== "string" || prompt.length === 0) {
    return undefined;
  }
  const markerIndexes = RETRY_CONTINUATION_MARKERS.map((marker) =>
    prompt.indexOf(marker),
  ).filter((index) => index !== -1);
  if (markerIndexes.length === 0) {
    return undefined;
  }
  const firstMarker = Math.min(...markerIndexes);
  // The instruction starts at the paragraph boundary preceding the marker.
  const boundary = prompt.lastIndexOf("\n\n", firstMarker);
  if (boundary === -1) {
    return { basePrompt: undefined };
  }
  const basePrompt = prompt.slice(0, boundary).trim();
  return { basePrompt: basePrompt.length > 0 ? basePrompt : undefined };
}

function safeLog(logger, level, fields) {
  const method = logger?.[level];
  if (typeof method !== "function") {
    return;
  }
  try {
    method.call(logger, JSON.stringify(fields));
  } catch {
    // Observability must never change the fail-closed decision.
  }
}

function failureClassOf(error) {
  return error instanceof CoreIntegrationError ? error.failureClass : "internal";
}

function contextualReferentFromOriginalTurn(originalTurn) {
  const text =
    typeof originalTurn?.replyToBody === "string"
      ? originalTurn.replyToBody.trim()
      : "";
  const messageId =
    typeof originalTurn?.replyToId === "string" ||
    typeof originalTurn?.replyToId === "number"
      ? String(originalTurn.replyToId)
      : "";
  if (!text || !messageId) return undefined;
  return {
    source: "quoted_message",
    message_id: messageId,
    text: text.slice(0, 12_000),
    ...(typeof originalTurn?.replyToSender === "string" &&
    originalTurn.replyToSender.trim()
      ? { sender: originalTurn.replyToSender.trim().slice(0, 256) }
      : {}),
  };
}

function corePromptForTelegramReply(cleanedBody) {
  if (typeof cleanedBody !== "string") {
    return cleanedBody;
  }
  const understoodMarker = "[Image understood:";
  const understoodIndex = cleanedBody.indexOf(understoodMarker);
  if (understoodIndex !== -1) {
    const caption = cleanedBody.slice(0, understoodIndex).trim();
    return caption.length > 0 ? caption : cleanedBody;
  }

  const imageMarker = "[Image]";
  const imageIndex = cleanedBody.indexOf(imageMarker);
  if (imageIndex === -1) {
    return cleanedBody;
  }

  // The runtime prompt may carry a session preamble before "[Image]", so the
  // envelope must be located rather than anchored to the start of the string.
  const envelopeBody = cleanedBody.slice(imageIndex + imageMarker.length);
  const imageEnvelope = /^\s*User text:\s*([\s\S]*?)\s*(?:\.\s*)?Description:\s*[\s\S]*$/;
  const envelopeMatch = envelopeBody.match(imageEnvelope);
  if (envelopeMatch?.[1] !== undefined) {
    let caption = envelopeMatch[1].trim();
    const telegramMeta = /^\[Telegram[^\]]*\]\s*(?:[^:\n]*:\s*)?([\s\S]*)$/;
    const metaMatch = caption.match(telegramMeta);
    if (metaMatch?.[1] !== undefined) {
      caption = metaMatch[1].trim();
      if (caption.startsWith("**") && caption.endsWith("**") && caption.length > 4) {
        caption = caption.slice(2, -2).trim();
      }
    }
    caption = caption.trim();
    if (caption.length > 0) {
      return caption;
    }
  }
  return cleanedBody;
}

export function createAnhDuongCoreHooks({
  env = process.env,
  fetchImpl = fetch,
  logger,
  now = () => Date.now(),
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  workflowProgressDelayMs = WORKFLOW_PROGRESS_DELAY_MS,
  workflowProgressCleanupPollMs = 1000,
  deleteWorkflowProgress,
  scheduleWorkflowCleanup,
  realpathImpl = realpathSync,
  statImpl = statSync,
  resolveOriginalTurn,
  loadActiveVisualReference = async () => undefined,
  storeActiveVisualReference = async () => undefined,
  loadRecentAssistantReferent = async () => undefined,
} = {}) {
  let config;
  let configFailure;
  try {
    config = readCoreConfig(env);
  } catch (error) {
    configFailure = error;
  }

  const explicitlyDisabled = config?.enabled === false;
  const states = new Map();
  const progress = new Map();

  function sweep() {
    const current = now();
    for (const [runId, state] of states) {
      if (state.expiresAt <= current) {
        states.delete(runId);
      }
    }
  }

  function findClaimablePreAgentState(ctx, prompt) {
    const sessionKey = ctx?.sessionKey ?? ctx?.sessionId;
    if (
      typeof sessionKey !== "string" ||
      sessionKey.length === 0 ||
      typeof prompt !== "string" ||
      prompt.length === 0
    ) {
      return undefined;
    }

    let candidate;
    for (const [stateRunId, state] of states) {
      if (
        state.status !== "prepared" ||
        state.provisionalSource !== "before_agent_reply" ||
        state.prepared.route_decision.route === "workflow" ||
        state.prompt !== prompt ||
        state.sessionKey !== sessionKey
      ) {
        continue;
      }
      if (
        typeof ctx?.chatId === "string" &&
        typeof state.chatId === "string" &&
        ctx.chatId !== state.chatId
      ) {
        continue;
      }
      if (
        typeof ctx?.senderId === "string" &&
        typeof state.senderId === "string" &&
        ctx.senderId !== state.senderId
      ) {
        continue;
      }
      if (candidate) {
        return undefined;
      }
      candidate = { runId: stateRunId, state };
    }
    return candidate;
  }

  function findPreparedDirectState(ctx, cleanedBody) {
    const sessionKey = ctx?.sessionKey ?? ctx?.sessionId;
    const chatId = ctx?.chatId;
    const senderId = ctx?.senderId;
    if (typeof cleanedBody !== "string" || cleanedBody.length === 0) {
      return undefined;
    }
    for (const [runId, state] of states) {
      const sameSession =
        typeof sessionKey === "string" && sessionKey.length > 0 && state.sessionKey === sessionKey;
      const sameTelegramActor =
        typeof chatId === "string" &&
        typeof senderId === "string" &&
        state.chatId === chatId &&
        state.senderId === senderId;
      const samePrompt =
        typeof state.prompt === "string" &&
        (cleanedBody.includes(state.prompt) || state.prompt.includes(cleanedBody));
      if (
        state.status === "prepared" &&
        state.prepared.route_decision.route !== "workflow" &&
        samePrompt &&
        (sameSession || sameTelegramActor)
      ) {
        return { runId, state };
      }
    }
    return undefined;
  }

  /**
   * Finds the most recent prepared, non-workflow state belonging to the same
   * Telegram session/actor, regardless of prompt text. Used only to recover the
   * original intent of a synthetic retry continuation.
   */
  function findReusableDirectState(ctx) {
    const sessionKey = ctx?.sessionKey ?? ctx?.sessionId;
    const chatId = ctx?.chatId;
    const senderId = ctx?.senderId;
    let candidate;
    for (const state of states.values()) {
      const sameSession =
        typeof sessionKey === "string" && sessionKey.length > 0 && state.sessionKey === sessionKey;
      const sameTelegramActor =
        typeof chatId === "string" &&
        typeof senderId === "string" &&
        state.chatId === chatId &&
        state.senderId === senderId;
      if (
        state.status === "prepared" &&
        state.prepared.route_decision.route !== "workflow" &&
        (sameSession || sameTelegramActor)
      ) {
        candidate = state;
      }
    }
    return candidate;
  }

  function messageText(message) {
    if (typeof message?.content === "string") return message.content;
    if (!Array.isArray(message?.content)) return undefined;
    const parts = message.content
      .map((part) => (typeof part?.text === "string" ? part.text : ""))
      .filter(Boolean);
    return parts.length > 0 ? parts.join("\n") : undefined;
  }

  function recentUserUrl(messages, currentText) {
    if (!Array.isArray(messages)) return undefined;
    for (const message of [...messages.slice(-8)].reverse()) {
      if (message?.role !== "user") continue;
      const text = messageText(message);
      if (typeof text !== "string" || text.trim() === String(currentText ?? "").trim()) continue;
      const matches = text.match(/https?:\/\/[^\s<>"']+/giu) ?? [];
      for (const raw of [...matches].reverse()) {
        const value = raw.replace(/[.,!?;:]+$/u, "");
        if (value.length === 0 || value.length > 2048) continue;
        try {
          const parsed = new URL(value);
          if ((parsed.protocol === "http:" || parsed.protocol === "https:") && !parsed.username && !parsed.password) {
            return { kind: "url", value };
          }
        } catch {}
      }
    }
    return undefined;
  }

  function trustedTelegramReplyImageReference(ctx, originalTurn) {
    const preservedPaths = Array.isArray(originalTurn?.mediaPaths) ? originalTurn.mediaPaths : [];
    const preservedTypes = Array.isArray(originalTurn?.mediaTypes) ? originalTurn.mediaTypes : [];
    const replyMedia = preservedPaths.length > 0
      ? preservedPaths.map((path, index) => ({ path, contentType: preservedTypes[index] }))
      : ctx?.channelContext?.chat?.replyMedia;
    if (!Array.isArray(replyMedia) || replyMedia.length === 0) return { status: "none" };

    const imageSuffix = /\.(?:png|jpe?g|webp|gif)$/i;
    for (const item of replyMedia) {
      if (typeof item?.path !== "string" || item.path.includes("\0") || typeof item?.contentType !== "string") {
        return { status: "invalid" };
      }
      if (!item.contentType.toLowerCase().startsWith("image/") && imageSuffix.test(item.path)) {
        return { status: "invalid" };
      }
    }
    const imageEntries = replyMedia.filter((item) => item.contentType.toLowerCase().startsWith("image/"));
    if (imageEntries.length === 0) return { status: "none" };
    if (imageEntries.length !== replyMedia.length) return { status: "invalid" };

    const mediaRoot = "/home/node/.openclaw/media/inbound";
    const uuidImageId = /^(?:[\p{L}\p{N}._-]+---)?[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.(?:png|jpe?g|webp|gif)$/iu;
    const references = [];
    for (const item of imageEntries) {
      const resolved = posixPath.resolve(item.path);
      const relative = posixPath.relative(mediaRoot, resolved);
      if (!relative || relative !== posixPath.basename(relative)) return { status: "invalid" };
      try {
        const canonicalRoot = realpathImpl(mediaRoot);
        const canonicalPath = realpathImpl(resolved);
        const canonicalRelative = posixPath.relative(canonicalRoot, canonicalPath);
        if (!canonicalRelative || canonicalRelative !== posixPath.basename(canonicalRelative)) return { status: "invalid" };
        if (canonicalPath !== resolved || !statImpl(canonicalPath).isFile()) return { status: "invalid" };
        const mediaId = posixPath.basename(resolved);
        if (!uuidImageId.test(mediaId)) return { status: "invalid" };
        references.push(`media://inbound/${encodeURIComponent(mediaId)}`);
      } catch {
        return { status: "invalid" };
      }
    }
    if (references.length > 1) return { status: "ambiguous" };
    return { status: "single", referenceImage: references[0] };
  }

  function trustedCurrentPromptImageReference(rawPrompt) {
    if (typeof rawPrompt !== "string") return { status: "none" };
    const markerPrefix = "[media attached:";
    const markerLines = rawPrompt.split("\n").filter((line) => line.startsWith(markerPrefix));
    if (markerLines.length === 0) return { status: "none" };

    const parsed = [];
    for (const line of markerLines) {
      const match = line.match(/^\[media attached: (.+) \(([^()]+)\)\]$/);
      if (!match) return { status: "invalid" };
      parsed.push({ stagedPath: match[1], contentType: match[2].toLowerCase() });
    }
    const imageEntries = parsed.filter((item) => item.contentType.startsWith("image/"));
    if (imageEntries.length === 0) return { status: "none" };
    if (imageEntries.length !== parsed.length) return { status: "invalid" };

    const stagedRoot = "/home/node/.openclaw/workspace/media/inbound";
    const mediaRoot = "/home/node/.openclaw/media/inbound";
    const uuidImageId = /^(?:[\p{L}\p{N}._-]+---)?[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.(?:png|jpe?g|webp|gif)$/iu;
    const references = [];
    for (const item of imageEntries) {
      const resolvedStaged = posixPath.resolve(item.stagedPath);
      const stagedRelative = posixPath.relative(stagedRoot, resolvedStaged);
      const parts = stagedRelative.split("/");
      if (parts.length !== 2 || !parts[0].startsWith("openclaw-staged-") || !parts[1]) return { status: "invalid" };
      const mediaId = parts[1];
      if (!uuidImageId.test(mediaId)) return { status: "invalid" };
      const managedPath = posixPath.join(mediaRoot, mediaId);
      try {
        const canonicalRoot = realpathImpl(mediaRoot);
        const canonicalPath = realpathImpl(managedPath);
        if (canonicalPath !== managedPath || posixPath.dirname(canonicalPath) !== canonicalRoot) return { status: "invalid" };
        if (!statImpl(canonicalPath).isFile()) return { status: "invalid" };
        references.push(`media://inbound/${encodeURIComponent(mediaId)}`);
      } catch {
        return { status: "invalid" };
      }
    }
    if (references.length > 1) return { status: "ambiguous" };
    return { status: "single", referenceImage: references[0] };
  }

  function resolveVisualImageProvenance(ctx, rawPrompt, originalTurn) {
    const preservedPaths = Array.isArray(originalTurn?.mediaPaths) ? originalTurn.mediaPaths : [];
    const hasPreservedMedia = preservedPaths.length > 0;
    const originalIsReply = originalTurn?.replyToId !== undefined && originalTurn?.replyToId !== null;
    const contextHasReplyMedia = !hasPreservedMedia && Array.isArray(ctx?.channelContext?.chat?.replyMedia);
    let source = originalIsReply || contextHasReplyMedia ? "replied_image" : "current_upload";
    let resolution = trustedTelegramReplyImageReference(ctx, originalTurn);
    if (resolution.status === "none") {
      resolution = trustedCurrentPromptImageReference(rawPrompt);
      source = "current_upload";
    }
    if (resolution.status === "invalid") {
      return { status: "invalid", imageSource: "none", referenceImage: undefined };
    }
    if (resolution.status === "ambiguous") {
      return { status: "ambiguous", imageSource: "ambiguous", referenceImage: undefined };
    }
    if (resolution.status === "single") {
      return { status: "single", imageSource: source, referenceImage: resolution.referenceImage };
    }
    return { status: "none", imageSource: "none", referenceImage: undefined };
  }

  function isVisualImageWorkflowState(state) {
    return (
      state?.prepared?.route_decision?.route === "workflow" &&
      state?.prepared?.capability_decision?.capability === "visual_image_generate"
    );
  }

  function approvalContinuationContext(text, ctx) {
    const originalTurn = resolveOriginalTurn?.({
      sessionKey: ctx?.sessionKey ?? ctx?.sessionId,
      senderId: ctx?.senderId,
      rawPrompt: text,
    });
    if (!originalTurn || originalTurn.ambiguous) return undefined;
    return {
      replyToId: originalTurn.replyToId,
      replyToBody: originalTurn.replyToBody,
    };
  }

  async function beforePromptBuild(event, ctx, { provisionalSource } = {}) {
    sweep();
    if (isTelegram(ctx)) {
      const approvalText = event?.prompt ?? event?.cleanedBody;
      const approval = parseApprovalIntent(approvalText);
      const continuation =
        !approval &&
        parseApprovalContinuation(
          approvalText,
          approvalContinuationContext(approvalText, ctx),
        );
      if (approval || continuation) {
        const approvalRunId = resolveTurnRunId(ctx, approvalText, now());
        const existingApproval = approvalRunId ? states.get(approvalRunId) : undefined;
        if (existingApproval?.status === "approval_resumed") {
          return {
            prependContext: existingApproval.preparedContext,
            _anhDuongApprovalResumed: true,
          };
        }
        if (configFailure || !config?.enabled) {
          return { prependContext: SAFE_MESSAGE };
        }
        try {
          const run = approval
            ? await resolveApproval({
                config,
                approvalId: approval.approvalId,
                payload: {
                  action: approval.action,
                  resolved_by: ctx?.senderId ?? "telegram",
                  approved: true,
                },
                fetchImpl,
              })
            : await resolveLatestApproval({
                config,
                payload: {
                  source_chat_id: String(ctx?.chatId ?? ""),
                  source_session_id: String(ctx?.sessionKey ?? ctx?.sessionId ?? ""),
                  resolved_by: String(ctx?.senderId ?? "telegram"),
                  approved: true,
                },
                fetchImpl,
              });
          const preparedContext = approval
            ? `Approval ${approval.approvalId} accepted; resumed run ${run.id}.`
            : "Approval accepted; resumed the latest Telegram task.";
          if (approvalRunId) {
            states.set(approvalRunId, {
              status: "approval_resumed",
              preparedContext,
              expiresAt: now() + STATE_TTL_MS,
            });
          }
          return { prependContext: preparedContext, _anhDuongApprovalResumed: true };
        } catch (error) {
          safeLog(logger, "warn", {
            event: "anh_duong_core_approval",
            outcome: "failure",
            failure_class: failureClassOf(error),
          });
          return { prependContext: SAFE_MESSAGE };
        }
      }
    }
    if (explicitlyDisabled || !isManagedChannel(ctx)) {
      return undefined;
    }

    const rawPrompt = event?.prompt;
    const originalTurn = resolveOriginalTurn?.({
      runId: ctx?.runId,
      sessionKey: ctx?.sessionKey ?? ctx?.sessionId,
      chatId: ctx?.chatId,
      senderId: ctx?.senderId,
      rawPrompt,
    });
    if (originalTurn?.ambiguous === true) {
      safeLog(logger, "warn", { event: "anh_duong_core_prepare", outcome: "failure", failure_class: "ambiguous_original_turn" });
      return undefined;
    }
    // Direct-owner provenance may come from either a native user hook with a UUID run id
    // or the trusted message_received snapshot for the same Telegram sender/session.
    // Never infer provenance from prompt text or a generated compatibility id alone.
    const currentChatId = normalizeTelegramChatTarget(ctx?.chatId);
    const originalChatId = normalizeTelegramChatTarget(originalTurn?.sourceChatId);
    const nativeUserTurn = ctx?.trigger === "user"
      && typeof ctx?.runId === "string"
      && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(ctx.runId)
      && typeof ctx?.senderId === "string" && /^[1-9][0-9]*$/.test(ctx.senderId)
      && typeof ctx?.chatId === "string" && ctx.chatId.length > 0
      && typeof ctx?.sessionKey === "string" && ctx.sessionKey.length > 0;
    const trustedInboundTurn = ctx?.trigger === "user"
      && originalTurn?.trustedTelegramInbound === true
      && typeof originalTurn?.sourceMessageId === "string"
      && /^[1-9][0-9]*$/.test(originalTurn.sourceMessageId)
      && typeof originalChatId === "string"
      && typeof currentChatId === "string"
      && currentChatId === originalChatId
      && typeof ctx?.senderId === "string"
      && /^[1-9][0-9]*$/.test(ctx.senderId)
      && typeof (ctx?.sessionKey ?? ctx?.sessionId) === "string";
    const directUserTurn = nativeUserTurn || trustedInboundTurn;
    const originalInstruction = typeof originalTurn?.text === "string" && originalTurn.text.trim()
      ? originalTurn.text.trim()
      : undefined;
    const retrySplit = splitRetryContinuation(rawPrompt);
    const isRetryContinuation = retrySplit !== undefined;
    // A synthetic continuation carries the original request as its prefix, so
    // Core must classify that original intent rather than the control text.
    const promptForCore =
      originalInstruction ??
      (isRetryContinuation && retrySplit.basePrompt !== undefined
        ? retrySplit.basePrompt
        : rawPrompt);
    const parsedPrompt = corePromptForTelegramReply(promptForCore);
    const corePrompt = parsedPrompt;
    const visualReference = resolveVisualImageProvenance(ctx, rawPrompt, originalTurn);
    if (visualReference.status === "invalid") {
      const referenceFailureClass = "invalid_reply_media";
      const invalidRunId = ctx?.runId;
      if (typeof invalidRunId === "string" && invalidRunId.length > 0) {
        states.set(invalidRunId, {
          status: "failed",
          failureClass: referenceFailureClass,
          expiresAt: now() + STATE_TTL_MS,
        });
      }
      safeLog(logger, "warn", {
        event: "anh_duong_core_prepare",
        outcome: "failure",
        failure_class: referenceFailureClass,
      });
      return undefined;
    }
    safeLog(logger, "info", {
      event: "anh_duong_core_prompt_shape",
      hook: "before_prompt_build",
      raw_length: typeof rawPrompt === "string" ? rawPrompt.length : -1,
      parsed_length: typeof corePrompt === "string" ? corePrompt.length : -1,
      image_prefix: typeof rawPrompt === "string" && rawPrompt.startsWith("[Image]"),
      image_index: typeof rawPrompt === "string" ? rawPrompt.indexOf("[Image]") : -1,
      user_text_index: typeof rawPrompt === "string" ? rawPrompt.indexOf("User text:") : -1,
      description_index: typeof rawPrompt === "string" ? rawPrompt.indexOf("Description:") : -1,
      parsed: corePrompt !== rawPrompt,
      retry_continuation: isRetryContinuation,
    });
    const runId = resolveTurnRunId(ctx, corePrompt, now());
    if (typeof runId !== "string" || runId.length === 0) {
      safeLog(logger, "warn", {
        event: "anh_duong_core_prepare",
        outcome: "failure",
        failure_class: "missing_run_id",
      });
      return undefined;
    }

    const existing = states.get(runId);
    if (existing?.status === "prepared") {
      return isVisualImageWorkflowState(existing) || existing.prepared.route_decision.route !== "workflow"
        ? { prependContext: existing.preparedContext }
        : undefined;
    }
    if (existing) {
      return undefined;
    }

    if (
      provisionalSource === undefined &&
      typeof ctx?.runId === "string" &&
      ctx.runId.length > 0
    ) {
      const provisional = findClaimablePreAgentState(ctx, corePrompt);
      if (provisional && provisional.runId !== runId) {
        const claimedState = {
          ...provisional.state,
          provisionalSource: undefined,
          expiresAt: now() + STATE_TTL_MS,
        };
        states.delete(provisional.runId);
        states.set(runId, claimedState);
        safeLog(logger, "info", {
          event: "anh_duong_core_prepare",
          outcome: "reused",
          reason: "pre_agent_prepare_claimed",
          request_id: provisional.state.requestId,
          route: provisional.state.prepared.route_decision.route,
          capability: provisional.state.prepared.capability_decision.capability,
          source_run_id: provisional.runId,
        });
        return { prependContext: claimedState.preparedContext };
      }
    }

    // AD-TXT-1: a synthetic retry continuation is never a new user intent. If the
    // per-run prepared state is no longer reachable (run teardown, distinct hook
    // instance, or a compat-keyed first turn), re-preparing would let Core
    // classify the imperative control text as a system operation and silently
    // downgrade an already-approved conversational turn into a blocked workflow.
    // Reuse the last prepared conversational state for this session instead.
    if (isRetryContinuation) {
      const matched = findPreparedDirectState(ctx, corePrompt);
      const reusable = matched?.state ?? findReusableDirectState(ctx);
      if (reusable) {
        states.set(runId, { ...reusable, expiresAt: now() + STATE_TTL_MS });
        safeLog(logger, "info", {
          event: "anh_duong_core_prepare",
          outcome: "reused",
          reason: "retry_continuation",
          ...(reusable.requestId ? { request_id: reusable.requestId } : {}),
          route: reusable.prepared.route_decision.route,
        });
        return { prependContext: reusable.preparedContext };
      }
    }

    states.set(runId, {
      status: "pending",
      expiresAt: now() + STATE_TTL_MS,
    });

    let requestId;
    try {
      if (configFailure || !config?.enabled) {
        throw configFailure ?? new CoreIntegrationError("configuration");
      }
      const request = buildCoreRequest({
        prompt: corePrompt,
        runId,
        senderId: ctx?.senderId,
        chatId: currentChatId,
        sessionKey: ctx?.sessionKey ?? ctx?.sessionId,
        imageSource: visualReference.imageSource,
        referenceImage: visualReference.referenceImage,
        recentImageCandidate: visualReference.referenceImage === undefined ? await loadActiveVisualReference(ctx) : undefined,
        channel: managedChannel(ctx),
        ...(directUserTurn ? { sourceOrigin: `${managedChannel(ctx)}_user` } : {}),
        ...(trustedInboundTurn ? { sourceMessageId: originalTurn.sourceMessageId } : {}),
        recentReferent: recentUserUrl(event?.messages, corePrompt),
        contextualReferent: contextualReferentFromOriginalTurn(originalTurn),
        recentAssistantCandidate: await loadRecentAssistantReferent(ctx),
      });
      requestId = request.request_id;
      const prepared = await prepareCoreRequest({ config, request, fetchImpl });
      const preparedContext = appendCapabilityPolicy(prepared, buildPreparedContext(prepared));
      if (typeof visualReference.referenceImage === "string") {
        await storeActiveVisualReference(ctx, visualReference.referenceImage);
      }
      states.set(runId, {
        status: "prepared",
        requestId,
        prepared,
        preparedContext,
        prompt: corePrompt,
        ownerSource: directUserTurn,
        sessionKey: ctx?.sessionKey ?? ctx?.sessionId,
        chatId: ctx?.chatId,
        senderId: ctx?.senderId,
        provisionalSource,
        visualReference,
        preparedAt: now(),
        expiresAt: now() + STATE_TTL_MS,
      });
      safeLog(logger, "info", {
        event: "anh_duong_core_prepare",
        outcome: "success",
        request_id: requestId,
        route: prepared.route_decision.route,
        capability: prepared.capability_decision.capability,
        execution_required: prepared.execution_required,
        ...(prepared.visual_interaction ? {
          visual_operation: prepared.visual_interaction.operation,
          image_source: prepared.visual_interaction.image_source,
          evidence_available: typeof prepared.visual_interaction.reference_image === "string",
        } : {}),
      });
      return { prependContext: preparedContext };
    } catch (error) {
      const failureClass = failureClassOf(error);
      states.set(runId, {
        status: "failed",
        requestId,
        failureClass,
        expiresAt: now() + STATE_TTL_MS,
      });
      safeLog(logger, "warn", {
        event: "anh_duong_core_prepare",
        outcome: "failure",
        ...(requestId ? { request_id: requestId } : {}),
        failure_class: failureClass,
        ...(Number.isInteger(error?.status) ? { http_status: error.status } : {}),
      });
      return undefined;
    }
  }

  async function beforeAgentReply(event, ctx) {
    sweep();
    const replyPrompt = event?.cleanedBody ?? event?.prompt;
    const isApprovalReply =
      isTelegram(ctx) &&
      !explicitlyDisabled &&
      (Boolean(parseApprovalIntent(replyPrompt)) ||
        parseApprovalContinuation(
          replyPrompt,
          approvalContinuationContext(replyPrompt, ctx),
        ));
    if (isApprovalReply) {
      const approvalResult = await beforePromptBuild(
        { prompt: replyPrompt, messages: [] },
        ctx,
      );
      if (approvalResult?._anhDuongApprovalResumed) {
        return {
          handled: true,
          reply: { text: APPROVAL_ACKNOWLEDGMENT },
          reason: "anh_duong_approval_resumed",
        };
      }
      return {
        handled: true,
        reply: { text: SAFE_MESSAGE },
        reason: "anh_duong_approval_failed",
      };
    }
    if (explicitlyDisabled || !isManagedChannel(ctx)) {
      return undefined;
    }
    const runId = resolveTurnRunId(ctx, event?.cleanedBody, now());
    if (typeof runId !== "string" || runId.length === 0) {
      return {
        handled: true,
        reply: { text: SAFE_MESSAGE },
        reason: "anh_duong_workflow_failed",
      };
    }

    const existing = states.get(runId);
    if (existing?.status === "submitted") {
      return {
        handled: true,
        reason: "anh_duong_workflow_duplicate_hook",
      };
    }

    const corePrompt = corePromptForTelegramReply(event?.cleanedBody);
    const preparedDirect = findPreparedDirectState(ctx, corePrompt);
    if (preparedDirect) {
      return undefined;
    }

    const provisionalSource =
      typeof ctx?.runId === "string" && ctx.runId.length > 0
        ? undefined
        : "before_agent_reply";
    await beforePromptBuild(
      { prompt: corePrompt, messages: [] },
      ctx?.runId === runId ? ctx : { ...ctx, runId },
      { provisionalSource },
    );
    const state = states.get(runId);
    if (state?.status === "submitted") {
      return {
        handled: true,
        reason: "anh_duong_workflow_duplicate_hook",
      };
    }
    if (state?.status !== "prepared") {
      return {
        handled: true,
        reply: { text: SAFE_MESSAGE },
        reason: "anh_duong_workflow_failed",
      };
    }
    if (state.prepared.route_decision.route !== "workflow") {
      return undefined;
    }

    try {
      const payload = buildAsyncTaskCreate(state.prepared);
      const accepted = await submitAsyncTask({
        config,
        payload,
        fetchImpl,
      });
      states.set(runId, {
        ...state,
        status: "submitted",
        accepted,
        expiresAt: now() + STATE_TTL_MS,
      });
      progress.set(`${state.sessionKey ?? ""}:${state.chatId ?? ""}`, {
        runId: accepted.run_id,
        requestId: state.requestId,
      });
      safeLog(logger, "info", {
        event: "anh_duong_core_async_submit",
        outcome: accepted.replayed ? "replayed" : "accepted",
        request_id: state.requestId,
        task_id: accepted.task_id,
        run_id: accepted.run_id,
        run_status: accepted.status,
      });
      if (accepted.replayed) {
        return {
          handled: true,
          reason: "anh_duong_workflow_replayed",
        };
      }
      if (accepted.status === "blocked") {
        return {
          handled: true,
          reason: "anh_duong_workflow_blocked",
        };
      }
      const progressDecision = await waitForWorkflowProgressDecision({
        accepted,
        requestId: state.requestId,
      });
      if (progressDecision.terminal) {
        return {
          handled: true,
          reason: "anh_duong_workflow_completed_before_progress",
        };
      }
      return {
        handled: true,
        reply: { text: WORKFLOW_ACKNOWLEDGMENT },
        reason: "anh_duong_workflow_progress_after_threshold",
      };
    } catch (error) {
      const failureClass = failureClassOf(error);
      states.set(runId, {
        status: "failed",
        requestId: state.requestId,
        failureClass,
        expiresAt: now() + STATE_TTL_MS,
      });
      safeLog(logger, "warn", {
        event: "anh_duong_core_async_submit",
        outcome: "failure",
        request_id: state.requestId,
        failure_class: failureClass,
        ...(Number.isInteger(error?.status)
          ? { http_status: error.status }
          : {}),
      });
      return {
        handled: true,
        reply: { text: SAFE_MESSAGE },
        reason: "anh_duong_workflow_failed",
      };
    }
  }

  async function waitForWorkflowProgressDecision({ accepted, requestId }) {
    const delayMs = Math.max(0, Number(workflowProgressDelayMs) || 0);
    if (delayMs > 0) {
      await sleep(delayMs);
    }
    try {
      const run = await getAsyncTaskRun({
        config,
        runId: accepted.run_id,
        requestId,
        fetchImpl,
      });
      return { terminal: TERMINAL_RUN_STATUSES.has(run.status) };
    } catch (error) {
      safeLog(logger, "warn", {
        event: "anh_duong_core_workflow_progress_probe",
        outcome: "failure",
        request_id: requestId,
        failure_class: failureClassOf(error),
        ...(Number.isInteger(error?.status) ? { http_status: error.status } : {}),
      });
      return { terminal: false };
    }
  }

  async function messageSent(event, ctx) {
    const channel = ctx?.channelId ?? ctx?.channel ?? event?.channelId ?? event?.channel;
    const content = event?.content ?? event?.text;
    const success = event?.success ?? event?.ok;
    const messageId = event?.messageId ?? event?.receipt?.primaryPlatformMessageId;
    const to = event?.to ?? event?.chatId ?? ctx?.conversationId;
    const sessionKey = event?.sessionKey ?? ctx?.sessionKey;
    if (channel !== "telegram" || content !== WORKFLOW_ACKNOWLEDGMENT || success === false || !messageId) return;
    const key = `${sessionKey ?? ""}:${to ?? ""}`;
    const item = progress.get(key);
    if (!item) return;
    const cleanup = deleteWorkflowProgress ?? ((target) => deleteTelegramWorkflowProgress(ctx?.api ?? {}, target));
    const task = (async () => {
      for (let i = 0; i < 60; i += 1) {
        const run = await getAsyncTaskRun({ config, runId: item.runId, requestId: item.requestId, fetchImpl });
        if (TERMINAL_RUN_STATUSES.has(run.status)) {
          await cleanup({ chatId: to, messageId });
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, Number(workflowProgressCleanupPollMs) || 0));
      }
    })();
    (scheduleWorkflowCleanup ?? ((promise) => promise))(task);
  }

  async function beforeAgentRun(_event, ctx) {
    sweep();
    if (explicitlyDisabled || !isManagedChannel(ctx)) {
      return undefined;
    }
    const runId = ctx?.runId;
    const state = typeof runId === "string" ? states.get(runId) : undefined;
    const stateKeyDigest =
      typeof runId === "string"
        ? createHash("sha256").update(runId).digest("hex").slice(0, 12)
        : "none";
    safeLog(logger, "info", {
      event: "anh_duong_core_gate",
      hook: "before_agent_run",
      state_key: stateKeyDigest,
      state_found: Boolean(state),
      state_status: state?.status ?? "missing",
      ...(state?.requestId ? { request_id: state.requestId } : {}),
      ...(state?.status === "prepared"
        ? {
            route: state.prepared.route_decision.route,
            capability: state.prepared.capability_decision.capability,
            execution_required: state.prepared.execution_required,
          }
        : {}),
    });
    if (
      state?.status === "prepared" &&
      state.prepared.route_decision.route !== "workflow"
    ) {
      return { outcome: "pass" };
    }
    return {
      outcome: "block",
      reason: "anh_duong_core_unavailable",
      category: "core_unavailable",
      message: SAFE_MESSAGE,
    };
  }

  async function beforeToolCall(event, ctx) {
    sweep();
    if (explicitlyDisabled) {
      return undefined;
    }
    const runId = ctx?.runId ?? event?.runId;
    const state = typeof runId === "string" ? states.get(runId) : undefined;
    if (state?.status !== "prepared") {
      return undefined;
    }
    const route = state.prepared.route_decision.route;
    const capability = state.prepared.capability_decision?.capability;
    if (capability === "visual_analysis") {
      const toolName = event?.toolName ?? ctx?.toolName;
      const operation = state.prepared.visual_interaction?.operation;
      if (operation === "search" && (toolName === "web_search" || toolName === "web_fetch")) {
        return undefined;
      }
      return {
        block: true,
        blockReason: operation === "search"
          ? "anh_duong_visual_search_read_only_tools"
          : "anh_duong_visual_analysis_no_tools",
      };
    }
    if (route === "web_read") {
      const toolName = event?.toolName ?? ctx?.toolName;
      if (toolName === "web_search" || toolName === "web_fetch" || toolName === "x_search") {
        return undefined;
      }
      return {
        block: true,
        blockReason: "anh_duong_web_read_turn_web_tools_only",
      };
    }
    if (route === "memory") {
      const toolName = event?.toolName ?? ctx?.toolName;
      if (toolName === "memory_search" || toolName === "memory_get") {
        return undefined;
      }
      return {
        block: true,
        blockReason: "anh_duong_memory_turn_memory_tools_only",
      };
    }
    if (state.prepared.execution_required === false) {
      return {
        block: true,
        blockReason:
          route === "direct"
            ? "anh_duong_direct_turn_no_tools"
            : route === "core_read"
              ? "anh_duong_core_read_turn_no_tools"
              : "anh_duong_non_execution_turn_no_tools",
      };
    }
    return undefined;
  }

  async function agentEnd(_event, ctx) {
    if (typeof ctx?.runId === "string") {
      const state = states.get(ctx.runId);
      if (!isVisualImageWorkflowState(state)) {
        states.delete(ctx.runId);
      } else {
        states.set(ctx.runId, { ...state, expiresAt: now() + STATE_TTL_MS });
      }
    }
    sweep();
  }

  return { beforeAgentReply, beforePromptBuild, beforeAgentRun, beforeToolCall, agentEnd };
}
