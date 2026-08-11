import assert from "node:assert/strict";
import test from "node:test";

import { readCoreConfig } from "../src/config.js";

const VALID_ENV = {
  ANH_DUONG_CORE_ENABLED: "true",
  ANH_DUONG_CORE_BASE_URL: "http://host.docker.internal:8790/",
  ANH_DUONG_CORE_INTERNAL_TOKEN: "unit-test-secret",
  ANH_DUONG_CORE_TIMEOUT_SECONDS: "10",
};

test("disabled integration preserves the legacy path without requiring credentials", () => {
  assert.deepEqual(readCoreConfig({ ANH_DUONG_CORE_ENABLED: "false" }), {
    enabled: false,
  });
});

test("enabled integration normalizes a valid finite configuration", () => {
  assert.deepEqual(readCoreConfig(VALID_ENV), {
    enabled: true,
    baseUrl: "http://host.docker.internal:8790",
    token: "unit-test-secret",
    timeoutMs: 10_000,
  });
});

for (const [name, override] of [
  ["missing enabled flag", { ANH_DUONG_CORE_ENABLED: undefined }],
  ["invalid enabled flag", { ANH_DUONG_CORE_ENABLED: "yes" }],
  ["missing base URL", { ANH_DUONG_CORE_BASE_URL: "" }],
  ["non-http base URL", { ANH_DUONG_CORE_BASE_URL: "file:///tmp/core" }],
  ["missing token", { ANH_DUONG_CORE_INTERNAL_TOKEN: "" }],
  ["zero timeout", { ANH_DUONG_CORE_TIMEOUT_SECONDS: "0" }],
  ["oversized timeout", { ANH_DUONG_CORE_TIMEOUT_SECONDS: "31" }],
  ["fractional timeout", { ANH_DUONG_CORE_TIMEOUT_SECONDS: "1.5" }],
]) {
  test(`enabled integration rejects ${name}`, () => {
    const env = { ...VALID_ENV, ...override };
    assert.throws(
      () => readCoreConfig(env),
      (error) => error?.name === "CoreIntegrationError" && error?.failureClass === "configuration",
    );
  });
}

test("configuration failures never expose the token", () => {
  const token = "never-print-this-token";
  assert.throws(
    () =>
      readCoreConfig({
        ...VALID_ENV,
        ANH_DUONG_CORE_INTERNAL_TOKEN: token,
        ANH_DUONG_CORE_TIMEOUT_SECONDS: "bad",
      }),
    (error) => !String(error).includes(token) && !JSON.stringify(error).includes(token),
  );
});
