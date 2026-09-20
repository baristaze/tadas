// The one client instance the whole app shares, built from the runtime config.
import { createClient } from "../api";
import { useSessionStore } from "../store/session";
import { runtimeConfig } from "./config";
import { forgetSession } from "./forgetSession";

export const api = createClient({
  baseUrl: runtimeConfig().apiUrl,
  app: "portal",
  appVersion: __APP_VERSION__,
  timeoutMs: runtimeConfig().requestTimeoutMs,
  retryAttempts: runtimeConfig().retryAttempts,
  retryBaseDelayMs: runtimeConfig().retryBaseDelayMs,
  getToken: () => useSessionStore.getState().token,
  onUnauthorized: forgetSession,
});
