import { createHash } from "node:crypto";
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
  if (route === "direct") {
    return `${preparedContext}\ntool_policy: no_tools\nevidence_policy: Do not call tools. If any tool attempt is blocked, do not claim that a tool was executed, checked, searched, read, or verified.`;
  }
  if (route === "core_read") {
    return `${preparedContext}\ntool_policy: no_tools\nevidence_policy: Answer only from the prepared current Core context. Do not call tools or claim evidence outside that context.`;
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
  const result = await runner([
    process.execPath, "/app/openclaw.mjs", "message", "delete",
    "--channel", "telegram", "--target", String(chatId),
    "--message-id", String(messageId),
  ], { timeoutMs: 10_000, cwd: "/app" });
  if (result?.code !== 0) {
    throw new Error("OpenClaw Telegram progress deletion failed.");
  }
}
const STATE_TTL_MS = 5 * 60 * 1_000;
const WORKFLOW_PROGRESS_DELAY_MS = 1_500;
const TERMINAL_RUN_STATUSES = new Set([
  "completed",
  "failed",
  "blocked",
  "cancelled",
]);

function isTelegram(ctx) {
  return ctx?.messageProvider === "telegram" || ctx?.channel === "telegram";
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
    const telegramMeta = /^\[Telegram[^\]]*\]\s*[^:\n]*:\s*([\s\S]*)$/;
    const metaMatch = caption.match(telegramMeta);
    if (metaMatch?.[1] !== undefined) {
      caption = metaMatch[1].trim();
    }
    caption = caption.replace(/\.\s*$/, "").trim();
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

  const VISUAL_IMAGE_FOLLOW_UPS = new Set([
    "day",
    "ok lam di",
    "tao di",
    "e tu tao di",
    "lam di",
    "nhu cai nay",
    "lam lai",
  ]);

  function normalizeFollowUp(text) {
    return text
      .normalize("NFD")
      .replace(/[đĐ]/g, "d")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim()
      .replace(/\s+/g, " ");
  }

  function isVisualImageFollowUp(text) {
    if (typeof text !== "string") return false;
    const normalized = normalizeFollowUp(text);
    return (
      VISUAL_IMAGE_FOLLOW_UPS.has(normalized) ||
      /\b(?:lam|tao|trien khai)\b.*\b(?:phuong an|mau|cai nay|dang bai|fb|facebook)\b/.test(normalized)
    );
  }

  function recentAssistantVisualContext(messages) {
    if (!Array.isArray(messages)) return undefined;
    const recentMessages = messages.slice(-6);
    for (const message of [...recentMessages].reverse()) {
      if (message?.role !== "assistant" || typeof message?.content !== "string") continue;
      const text = message.content.trim();
      const normalized = normalizeFollowUp(text);
      const hasVisualSignal =
        /hình ảnh/iu.test(text) ||
        /\b(?:photo|picture|poster|banner|thumbnail)\b/i.test(text) ||
        /\b(?:create|generate|make|design|render)\s+(?:an?\s+|the\s+)?image\b/i.test(text) ||
        /(?:^|[^\p{L}\p{N}_])(?:tạo|làm|chốt|thiết kế|prompt)\s+(?:1\s+|một\s+)?(?:ảnh(?!\s+hưởng(?:$|[^\p{L}\p{N}_]))|hình ảnh|poster|banner|thumbnail)(?=$|[^\p{L}\p{N}_])/iu.test(text) ||
        /(?:^|[^\p{L}\p{N}_])ảnh\s+(?:dọc|ngang|vuông|thời trang|quảng cáo|minh họa|sản phẩm|facebook|tiktok|reels|bìa|cover)(?=$|[^\p{L}\p{N}_])/iu.test(text);
      if (hasVisualSignal) {
        return text.slice(0, 4000);
      }
    }
    return undefined;
  }

  function contextualVisualImagePrompt(text, messages) {
    if (!isVisualImageFollowUp(text)) return text;
    const context = recentAssistantVisualContext(messages);
    if (!context) return text;
    return `Tạo ảnh theo phương án đã chốt. Ngữ cảnh trước đó: ${context}\nYêu cầu hiện tại: ${text}`;
  }

  function isVisualImageWorkflowState(state) {
    return (
      state?.prepared?.route_decision?.route === "workflow" &&
      state?.prepared?.capability_decision?.capability === "visual_image_generate"
    );
  }

  function stateBelongsToTelegramContext(state, ctx) {
    const sessionKey = ctx?.sessionKey ?? ctx?.sessionId;
    const sameSession =
      typeof sessionKey === "string" &&
      sessionKey.length > 0 &&
      state.sessionKey === sessionKey;
    const sameTelegramActor =
      typeof ctx?.chatId === "string" &&
      typeof ctx?.senderId === "string" &&
      state.chatId === ctx.chatId &&
      state.senderId === ctx.senderId;
    return sameSession || sameTelegramActor;
  }

  function findReusableVisualImageState(ctx) {
    const candidates = [];
    for (const [runId, state] of states) {
      if (!["prepared", "submitted"].includes(state.status)) continue;
      if (!isVisualImageWorkflowState(state)) continue;
      if (stateBelongsToTelegramContext(state, ctx)) {
        candidates.push({ runId, state });
      }
    }
    return candidates.length === 1 ? candidates[0] : undefined;
  }

  async function beforePromptBuild(event, ctx) {
    sweep();
    if (isTelegram(ctx)) {
      const approvalText = event?.prompt ?? event?.cleanedBody;
      const approval = parseApprovalIntent(approvalText);
      const continuation = !approval && parseApprovalContinuation(approvalText);
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
    if (explicitlyDisabled || !isTelegram(ctx)) {
      return undefined;
    }

    const rawPrompt = event?.prompt;
    const retrySplit = splitRetryContinuation(rawPrompt);
    const isRetryContinuation = retrySplit !== undefined;
    // A synthetic continuation carries the original request as its prefix, so
    // Core must classify that original intent rather than the control text.
    const promptForCore =
      isRetryContinuation && retrySplit.basePrompt !== undefined
        ? retrySplit.basePrompt
        : rawPrompt;
    const parsedPrompt = corePromptForTelegramReply(promptForCore);
    const corePrompt = contextualVisualImagePrompt(parsedPrompt, event?.messages);
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

    if (isVisualImageFollowUp(corePrompt)) {
      const reusable = findReusableVisualImageState(ctx);
      if (reusable) {
        const reusedState = {
          ...reusable.state,
          prompt: corePrompt,
          expiresAt: now() + STATE_TTL_MS,
        };
        if (reusable.runId !== runId) {
          states.delete(reusable.runId);
        }
        states.set(runId, reusedState);
        safeLog(logger, "info", {
          event: "anh_duong_core_prepare",
          outcome: "reused",
          reason: "visual_image_follow_up",
          request_id: reusable.state.requestId,
          route: reusable.state.prepared.route_decision.route,
          capability: reusable.state.prepared.capability_decision.capability,
          source_run_id: reusable.runId,
        });
        return { prependContext: reusedState.preparedContext };
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
        chatId: ctx?.chatId,
        sessionKey: ctx?.sessionKey,
      });
      requestId = request.request_id;
      const prepared = await prepareCoreRequest({ config, request, fetchImpl });
      const preparedContext = appendCapabilityPolicy(prepared, buildPreparedContext(prepared));
      states.set(runId, {
        status: "prepared",
        requestId,
        prepared,
        preparedContext,
        prompt: corePrompt,
        sessionKey: ctx?.sessionKey ?? ctx?.sessionId,
        chatId: ctx?.chatId,
        senderId: ctx?.senderId,
        expiresAt: now() + STATE_TTL_MS,
      });
      safeLog(logger, "info", {
        event: "anh_duong_core_prepare",
        outcome: "success",
        request_id: requestId,
        route: prepared.route_decision.route,
        capability: prepared.capability_decision.capability,
        execution_required: prepared.execution_required,
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
      (Boolean(parseApprovalIntent(replyPrompt)) || parseApprovalContinuation(replyPrompt));
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
    if (explicitlyDisabled || !isTelegram(ctx)) {
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

    await beforePromptBuild(
      { prompt: corePrompt, messages: [] },
      ctx?.runId === runId ? ctx : { ...ctx, runId },
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
    if (explicitlyDisabled || !isTelegram(ctx)) {
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
