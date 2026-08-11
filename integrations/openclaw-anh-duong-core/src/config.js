export class CoreIntegrationError extends Error {
  constructor(failureClass, { status, requestId } = {}) {
    super(`Ánh Dương Core integration failed (${failureClass})`);
    this.name = "CoreIntegrationError";
    this.failureClass = failureClass;
    if (Number.isInteger(status)) {
      this.status = status;
    }
    if (typeof requestId === "string" && requestId.length > 0) {
      this.requestId = requestId;
    }
  }

  toJSON() {
    return {
      name: this.name,
      failureClass: this.failureClass,
      ...(this.status === undefined ? {} : { status: this.status }),
      ...(this.requestId === undefined ? {} : { requestId: this.requestId }),
    };
  }
}

function configurationError() {
  return new CoreIntegrationError("configuration");
}

export function readCoreConfig(env = process.env) {
  const enabled = env.ANH_DUONG_CORE_ENABLED;
  if (enabled === "false") {
    return { enabled: false };
  }
  if (enabled !== "true") {
    throw configurationError();
  }

  const token = env.ANH_DUONG_CORE_INTERNAL_TOKEN;
  if (typeof token !== "string" || token.length === 0) {
    throw configurationError();
  }

  let url;
  try {
    url = new URL(env.ANH_DUONG_CORE_BASE_URL);
  } catch {
    throw configurationError();
  }
  if ((url.protocol !== "http:" && url.protocol !== "https:") || url.username || url.password) {
    throw configurationError();
  }
  if (url.pathname !== "/" || url.search || url.hash) {
    throw configurationError();
  }

  const timeoutSeconds = Number(env.ANH_DUONG_CORE_TIMEOUT_SECONDS);
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 30) {
    throw configurationError();
  }

  return {
    enabled: true,
    baseUrl: url.origin,
    token,
    timeoutMs: timeoutSeconds * 1_000,
  };
}
