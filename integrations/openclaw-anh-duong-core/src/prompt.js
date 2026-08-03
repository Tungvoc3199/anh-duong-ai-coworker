import { CoreIntegrationError } from "./config.js";

export function buildPreparedContext(prepared) {
  const rendered = prepared?.context?.rendered_context;
  if (typeof rendered !== "string" || rendered.length === 0 || rendered.length > 100_000) {
    throw new CoreIntegrationError("validation", { requestId: prepared?.request_id });
  }

  return [
    "<anh_duong_core_prepared_request>",
    `request_id: ${prepared.request_id}`,
    `route: ${prepared.route_decision.route}`,
    `capability: ${prepared.capability_decision.capability}`,
    `execution_required: ${prepared.execution_required}`,
    "core_context:",
    rendered,
    "</anh_duong_core_prepared_request>",
  ].join("\n");
}
