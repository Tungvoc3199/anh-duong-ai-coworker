import { createHash } from "node:crypto";
import { CoreIntegrationError, readCoreConfig } from "./config.js";
import {
  buildAsyncTaskCreate,
  buildCoreRequest,
  prepareCoreRequest,
  submitAsyncTask,
} from "./core-client.js";
import { buildPreparedContext } from "./prompt.js";

export const SAFE_MESSAGE =
  "Ánh Dương Core hiện chưa sẵn sàng xử lý yêu cầu này. Vui lòng thử lại sau.";

export const WORKFLOW_ACKNOWLEDGMENT =
  "Em đã nhận việc và đang xử lý. Em sẽ báo lại ngay khi hoàn tất.";

const STATE_TTL_MS = 5 * 60 * 1_000;

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

  async function beforePromptBuild(event, ctx) {
    sweep();
    if (explicitlyDisabled || !isTelegram(ctx)) {
      return undefined;
    }

    const rawPrompt = event?.prompt;
    const corePrompt = corePromptForTelegramReply(rawPrompt);
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
      return {
        handled: true,
        reply: { text: WORKFLOW_ACKNOWLEDGMENT },
        reason: "anh_duong_workflow_accepted",
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
