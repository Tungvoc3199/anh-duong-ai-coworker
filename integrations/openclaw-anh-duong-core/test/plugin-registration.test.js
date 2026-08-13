import assert from "node:assert/strict";
import test from "node:test";

import plugin from "../index.js";

function registrationsFor(api) {
  const registrations = [];
  api.on = (name, handler, options) => {
    registrations.push({ name, handler, options });
  };
  plugin.register(api);
  return registrations;
}

test("message_received attachment observation is registered without runtime command helper", () => {
  const registrations = registrationsFor({
    logger: {},
    pluginConfig: {},
    runtime: { system: {} },
  });

  assert.equal(
    registrations.some((item) => item.name === "message_received"),
    true,
  );
  assert.equal(
    registrations.some((item) => item.name === "message_sent"),
    false,
  );
});

test("message_sent progress cleanup remains conditional on runtime command helper", () => {
  const registrations = registrationsFor({
    logger: {},
    pluginConfig: {},
    runtime: {
      system: {
        runCommandWithTimeout: async () => ({ code: 0 }),
      },
    },
  });

  assert.equal(
    registrations.some((item) => item.name === "message_received"),
    true,
  );
  assert.equal(
    registrations.some((item) => item.name === "message_sent"),
    true,
  );
});
