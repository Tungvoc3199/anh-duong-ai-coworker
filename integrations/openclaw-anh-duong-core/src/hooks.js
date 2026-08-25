import { createHash } from "node:crypto";
import { CoreIntegrationError, readCoreConfig } from "./config.js";
import {
  buildAsyncTaskCreate,
  getAsyncTaskRun,
  buildCoreRequest,
  parseApprovalIntent,
  prepareCoreRequest,
  resolveApproval,
  submitAsyncTask,
} from "./core-client.js";
import { buildPreparedContext } from "./prompt.js";

export const SAFE_MESSAGE =
  "Ánh Dương Core hiện chưa sẵn sàng xử lý yêu cầu này. Vui lòng thử lại sau.";

export const WORKFLOW_ACKNOWLEDGMENT =
  "Em đã nhận việc và đang xử lý. Em sẽ báo lại ngay khi hoàn tất.";
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

  async function beforePromptBuild(event, ctx) {
    sweep();
    if (isTelegram(ctx)) {
      const approval = parseApprovalIntent(event?.prompt ?? event?.cleanedBody);
      if (approval) {
        try {
          const run = await resolveApproval({
            config,
            approvalId: approval.approvalId,
            payload: {
              action: approval.action,
              resolved_by: ctx?.senderId ?? "telegram",
              approved: true,
            },
          });
          return { prependContext: `Approval ${approval.approvalId} accepted; resumed run ${run.id}.` };
        } catch (error) {
          safeLog(logger, "warn", { event: "anh_duong_core_approval", outcome: "failure", failure_class: failureClassOf(error) });
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
    const corePrompt = corePromptForTelegramReply(promptForCore);
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
      return existing.prepared.route_decision.route === "workflow"
        ? undefined
        : { prependContext: existing.preparedContext };
    }
    if (existing) {
      return undefined;
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
      const preparedContext = buildPreparedContext(prepared);
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

  async function agentEnd(_event, ctx) {
    if (typeof ctx?.runId === "string") {
      states.delete(ctx.runId);
    }
    sweep();
  }

  return { beforeAgentReply, beforePromptBuild, beforeAgentRun, agentEnd };
}
