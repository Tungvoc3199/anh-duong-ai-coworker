import assert from "node:assert/strict";
import test from "node:test";

import plugin, { deleteTelegramWorkflowProgress } from "../index.js";

test("Telegram progress cleanup uses the v2026.7.1 argv contract", async () => {
  const calls = [];
  const api = {
    runtime: {
      system: {
        async runCommandWithTimeout(...args) {
          calls.push(args);
          return { code: 0, stdout: "", stderr: "" };
        },
      },
    },
  };

  await deleteTelegramWorkflowProgress(api, {
    chatId: "private-chat",
    messageId: "3170",
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].length, 2);
  assert.deepEqual(calls[0][0], [
    process.execPath,
    "/app/openclaw.mjs",
    "message",
    "delete",
    "--channel",
    "telegram",
    "--target",
    "private-chat",
    "--message-id",
    "3170",
  ]);
  assert.deepEqual(calls[0][1], { timeoutMs: 10_000, cwd: "/app" });
});

test("plugin adds message_sent cleanup without replacing existing hooks", () => {
  const registered = new Set();
  plugin.register({
    logger: {},
    runtime: { system: { runCommandWithTimeout: async () => ({ code: 0 }) } },
    on(name) {
      registered.add(name);
    },
  });

  for (const name of [
    "before_agent_reply",
    "before_prompt_build",
    "before_agent_run",
    "agent_end",
    "message_sent",
  ]) {
    assert.ok(registered.has(name), name);
  }
});
