import { CoreIntegrationError } from "./config.js";

export function buildPreparedContext(prepared) {
  const rendered = prepared?.context?.rendered_context;
  if (typeof rendered !== "string" || rendered.length === 0 || rendered.length > 100_000) {
    throw new CoreIntegrationError("validation", { requestId: prepared?.request_id });
  }

  const visual = prepared?.visual_interaction;
  const visualLines = visual
    ? [
        `visual_operation: ${visual.operation}`,
        `visual_image_source: ${visual.image_source}`,
        `visual_image_role: ${visual.image_role ?? "none"}`,
        `visual_output: ${visual.output}`,
        `visual_constraints: ${(visual.constraints ?? []).join(",") || "none"}`,
        `visual_side_effect: ${visual.side_effect}`,
        `visual_clarification_required: ${visual.clarification_required}`,
        `visual_evidence_available: ${typeof visual.reference_image === "string"}`,
      ]
    : [];

  return [
    "<anh_duong_core_prepared_request>",
    `request_id: ${prepared.request_id}`,
    `route: ${prepared.route_decision.route}`,
    `capability: ${prepared.capability_decision.capability}`,
    `execution_required: ${prepared.execution_required}`,
    ...visualLines,
    "core_context:",
    rendered,
    "</anh_duong_core_prepared_request>",
  ].join("\n");
}
