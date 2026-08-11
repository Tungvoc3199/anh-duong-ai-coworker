import { createAnhDuongCoreHooks } from "./src/hooks.js";

const PROMPT_HOOK_TIMEOUT_MS = 32_000;
const WORKFLOW_HOOK_TIMEOUT_MS = 65_000;
const GATE_HOOK_TIMEOUT_MS = 2_000;

export default {
  id: "anh-duong-core",
  name: "Ánh Dương Core Gate",
  description: "Fail-closed Core preparation gate for ordinary Telegram agent turns.",
  register(api) {
    const hooks = createAnhDuongCoreHooks({ logger: api.logger });
    api.on("before_agent_reply", hooks.beforeAgentReply, {
      priority: 100,
      timeoutMs: WORKFLOW_HOOK_TIMEOUT_MS,
    });
    api.on("before_prompt_build", hooks.beforePromptBuild, {
      priority: 100,
      timeoutMs: PROMPT_HOOK_TIMEOUT_MS,
    });
    api.on("before_agent_run", hooks.beforeAgentRun, {
      priority: 100,
      timeoutMs: GATE_HOOK_TIMEOUT_MS,
    });
    api.on("agent_end", hooks.agentEnd, { priority: 100 });
  },
};
