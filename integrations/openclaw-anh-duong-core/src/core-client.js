import { createHash } from "node:crypto";

import { CoreIntegrationError } from "./config.js";

const ROUTES = new Set(["direct", "memory", "core_read", "workflow"]);
const CAPABILITIES = new Set([
  "conversational_response",
  "memory_search",
  "project_read",
  "task_read",
  "core_status_read",
  "planning",
  "file_operation",
  "code_operation",
  "external_communication",
  "system_operation",
  "unknown_workflow",
]);
const MODES = new Set(["quick", "build"]);
const PRIORITIES = new Set(["low", "normal", "high", "critical"]);
const POLICY_DECISIONS = new Set(["allow", "require_approval", "deny", "escalate"]);
const ASYNC_STATUSES = new Set(["pending", "blocked"]);
const ASYNC_RUN_STATUSES = new Set([
  "pending",
  "running",
  "retry_scheduled",
  "verifying",
  "completed",
  "failed",
  "blocked",
  "cancelled",
]);

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function validationError(requestId) {
  return new CoreIntegrationError("validation", { requestId });
}

function requireObject(value, requestId) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw validationError(requestId);
  }
  return value;
}

function requireString(value, requestId, { maxLength } = {}) {
  if (typeof value !== "string" || value.length === 0 || (maxLength && value.length > maxLength)) {
    throw validationError(requestId);
  }
  return value;
}

function requireStringArray(value, requestId) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw validationError(requestId);
  }
  return value;
}

function requireBoolean(value, requestId) {
  if (typeof value !== "boolean") {
    throw validationError(requestId);
  }
  return value;
}

function requireInteger(value, requestId, { min, max }) {
  if (!Number.isInteger(value) || value < min || value > max) {
    throw validationError(requestId);
  }
  return value;
}

function requireNullableString(value, requestId, options) {
  return value === null ? null : requireString(value, requestId, options);
}

export function buildCoreRequest({ prompt, runId, senderId, chatId, sessionKey }) {
  if (typeof prompt !== "string" || prompt.trim().length === 0 || prompt.length > 20_000) {
    throw validationError();
  }
  if (typeof runId !== "string" || runId.trim().length === 0) {
    throw validationError();
  }

  const directRequestId = `tg-${runId}`;
  const requestId = directRequestId.length <= 128 ? directRequestId : `tg-${sha256(runId)}`;
  const actor =
    typeof senderId === "string" && senderId.length > 0
      ? `telegram:${sha256(senderId)}`
      : "telegram:anonymous";
  const sourceMessageId =
    runId.length <= 128 ? runId : `message-${sha256(runId)}`;

  return {
    text: prompt,
    request_id: requestId,
    channel: "telegram",
    actor,
    ...(typeof chatId === "string" && chatId.length > 0
      ? { source_chat_id: chatId }
      : {}),
    ...(typeof sessionKey === "string" && sessionKey.length > 0
      ? { source_session_id: sessionKey }
      : {}),
    source_message_id: sourceMessageId,
  };
}

function validateWorkflowEnvelope(value, requestId) {
  const workflow = requireObject(value, requestId);
  const projectId = requireString(workflow.project_id, requestId, { maxLength: 64 });
  requireString(workflow.title, requestId, { maxLength: 255 });
  requireString(workflow.goal, requestId, { maxLength: 20_000 });
  if (!MODES.has(requireString(workflow.mode, requestId))) {
    throw validationError(requestId);
  }
  if (!PRIORITIES.has(requireString(workflow.priority, requestId))) {
    throw validationError(requestId);
  }
  requireInteger(workflow.risk_level, requestId, { min: 0, max: 4 });
  requireBoolean(workflow.approval_required, requestId);
  requireNullableString(workflow.workspace, requestId, { maxLength: 1024 });
  requireString(workflow.requested_by, requestId, { maxLength: 128 });
  if (requireString(workflow.source_channel, requestId, { maxLength: 64 }) !== "telegram") {
    throw validationError(requestId);
  }
  requireString(workflow.source_chat_id, requestId, { maxLength: 128 });
  requireString(workflow.source_session_id, requestId, { maxLength: 128 });
  requireString(workflow.source_message_id, requestId, { maxLength: 128 });
  const idempotencyKey = requireString(workflow.idempotency_key, requestId, { maxLength: 255 });
  if (!idempotencyKey.startsWith("telegram:")) {
    throw validationError(requestId);
  }
  if (requireString(workflow.correlation_id, requestId, { maxLength: 128 }) !== requestId) {
    throw validationError(requestId);
  }
  requireStringArray(workflow.constraints, requestId);
  if (!POLICY_DECISIONS.has(requireString(workflow.policy_decision, requestId))) {
    throw validationError(requestId);
  }
  requireString(workflow.policy_rule_id, requestId, { maxLength: 128 });
  requireString(workflow.policy_reason, requestId, { maxLength: 2000 });
  return { workflow, projectId };
}

export function validatePreparedRequest(value, expectedRequestId) {
  const root = requireObject(value, expectedRequestId);
  const requestId = requireString(root.request_id, expectedRequestId, { maxLength: 128 });
  if (requestId !== expectedRequestId) {
    throw validationError(expectedRequestId);
  }
  requireString(root.normalized_text, expectedRequestId, { maxLength: 20_000 });

  const persona = requireObject(root.persona, expectedRequestId);
  requireString(persona.version, expectedRequestId);
  if (!/^[0-9a-f]{64}$/.test(requireString(persona.content_hash, expectedRequestId))) {
    throw validationError(expectedRequestId);
  }

  const routeDecision = requireObject(root.route_decision, expectedRequestId);
  const route = requireString(routeDecision.route, expectedRequestId);
  if (!ROUTES.has(route)) {
    throw validationError(expectedRequestId);
  }
  requireString(routeDecision.rule_id, expectedRequestId);
  requireString(routeDecision.reason, expectedRequestId);

  const capabilityDecision = requireObject(root.capability_decision, expectedRequestId);
  const capability = requireString(capabilityDecision.capability, expectedRequestId);
  if (!CAPABILITIES.has(capability)) {
    throw validationError(expectedRequestId);
  }
  if (capabilityDecision.source_route !== route) {
    throw validationError(expectedRequestId);
  }
  requireString(capabilityDecision.reason_code, expectedRequestId);
  requireStringArray(capabilityDecision.matched_signals, expectedRequestId);

  const context = requireObject(root.context, expectedRequestId);
  requireString(context.rendered_context, expectedRequestId);
  if (typeof root.execution_required !== "boolean") {
    throw validationError(expectedRequestId);
  }
  if ((route === "workflow") !== root.execution_required) {
    throw validationError(expectedRequestId);
  }
  if (route === "workflow") {
    const { projectId } = validateWorkflowEnvelope(root.workflow, expectedRequestId);
    if (root.project_id !== projectId) {
      throw validationError(expectedRequestId);
    }
  } else if (root.workflow !== null && root.workflow !== undefined) {
    throw validationError(expectedRequestId);
  }
  requireStringArray(root.warnings, expectedRequestId);

  const provenance = requireObject(root.provenance, expectedRequestId);
  requireString(provenance.persona_version, expectedRequestId);
  if (!/^[0-9a-f]{64}$/.test(requireString(provenance.persona_content_hash, expectedRequestId))) {
    throw validationError(expectedRequestId);
  }
  requireString(provenance.route_rule_id, expectedRequestId);
  requireString(provenance.capability_reason_code, expectedRequestId);
  requireStringArray(provenance.context_source_refs, expectedRequestId);

  const createdAt = requireString(root.created_at, expectedRequestId);
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(createdAt) || Number.isNaN(Date.parse(createdAt))) {
    throw validationError(expectedRequestId);
  }

  return root;
}

export function buildAsyncTaskCreate(prepared) {
  const requestId = prepared?.request_id;
  if (prepared?.route_decision?.route !== "workflow" || prepared?.execution_required !== true) {
    throw validationError(requestId);
  }
  const { workflow } = validateWorkflowEnvelope(prepared.workflow, requestId);
  return {
    project_id: workflow.project_id,
    title: workflow.title,
    goal: workflow.goal,
    mode: workflow.mode,
    priority: workflow.priority,
    risk_level: workflow.risk_level,
    approval_required: workflow.approval_required,
    workspace: workflow.workspace,
    requested_by: workflow.requested_by,
    source_channel: workflow.source_channel,
    source_chat_id: workflow.source_chat_id,
    source_session_id: workflow.source_session_id,
    source_message_id: workflow.source_message_id,
    idempotency_key: workflow.idempotency_key,
    correlation_id: workflow.correlation_id,
    constraints: workflow.constraints,
    ...(workflow.governed_coding !== undefined
      ? { governed_coding: workflow.governed_coding }
      : {}),
  };
}

export function validateAsyncTaskAccepted(value, requestId) {
  const root = requireObject(value, requestId);
  requireString(root.task_id, requestId, { maxLength: 64 });
  requireString(root.run_id, requestId, { maxLength: 64 });
  if (!ASYNC_STATUSES.has(requireString(root.status, requestId))) {
    throw validationError(requestId);
  }
  requireString(root.message, requestId);
  requireBoolean(root.replayed, requestId);
  return root;
}

export function validateAsyncTaskRun(value, requestId) {
  const root = requireObject(value, requestId);
  const status = requireString(root.status, requestId);
  if (!ASYNC_RUN_STATUSES.has(status)) {
    throw validationError(requestId);
  }
  return root;
}

export async function prepareCoreRequest({ config, request, fetchImpl = fetch }) {
  const requestId = request?.request_id;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);

  try {
    let response;
    try {
      response = await fetchImpl(`${config.baseUrl}/api/internal/requests/prepare`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${config.token}`,
        },
        body: JSON.stringify(request),
        signal: controller.signal,
      });
    } catch {
      if (controller.signal.aborted) {
        throw new CoreIntegrationError("timeout", { requestId });
      }
      throw new CoreIntegrationError("connection", { requestId });
    }

    if (!response || typeof response.status !== "number" || typeof response.json !== "function") {
      throw validationError(requestId);
    }
    if (!response.ok) {
      const failureClass = response.status === 401 || response.status === 403 ? "authentication" : "http";
      throw new CoreIntegrationError(failureClass, { status: response.status, requestId });
    }

    let value;
    try {
      value = await response.json();
    } catch {
      throw validationError(requestId);
    }
    return validatePreparedRequest(value, requestId);
  } finally {
    clearTimeout(timer);
  }
}

export async function submitAsyncTask({ config, payload, fetchImpl = fetch }) {
  const requestId = payload?.correlation_id;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);

  try {
    let response;
    try {
      response = await fetchImpl(`${config.baseUrl}/api/async-tasks`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${config.token}`,
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch {
      if (controller.signal.aborted) {
        throw new CoreIntegrationError("timeout", { requestId });
      }
      throw new CoreIntegrationError("connection", { requestId });
    }

    if (!response || typeof response.status !== "number" || typeof response.json !== "function") {
      throw validationError(requestId);
    }
    if (response.status !== 202) {
      const failureClass = response.status === 401 || response.status === 403 ? "authentication" : "http";
      throw new CoreIntegrationError(failureClass, { status: response.status, requestId });
    }

    let value;
    try {
      value = await response.json();
    } catch {
      throw validationError(requestId);
    }
    return validateAsyncTaskAccepted(value, requestId);
  } finally {
    clearTimeout(timer);
  }
}

export async function getAsyncTaskRun({ config, runId, requestId, fetchImpl = fetch }) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);

  try {
    let response;
    try {
      response = await fetchImpl(`${config.baseUrl}/api/async-tasks/${encodeURIComponent(runId)}`, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${config.token}`,
        },
        signal: controller.signal,
      });
    } catch {
      if (controller.signal.aborted) {
        throw new CoreIntegrationError("timeout", { requestId });
      }
      throw new CoreIntegrationError("connection", { requestId });
    }

    if (!response || typeof response.status !== "number" || typeof response.json !== "function") {
      throw validationError(requestId);
    }
    if (!response.ok) {
      const failureClass = response.status === 401 || response.status === 403 ? "authentication" : "http";
      throw new CoreIntegrationError(failureClass, { status: response.status, requestId });
    }

    let value;
    try {
      value = await response.json();
    } catch {
      throw validationError(requestId);
    }
    return validateAsyncTaskRun(value, requestId);
  } finally {
    clearTimeout(timer);
  }
}
