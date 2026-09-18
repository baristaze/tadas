// The one client instance the whole app shares, built from the runtime config.
import { createClient } from "../api";
import { useSessionStore } from "../store/session";
import { runtimeConfig } from "./config";

export const api = createClient({
  baseUrl: runtimeConfig().apiUrl,
  app: "portal",
  appVersion: __APP_VERSION__,
  getToken: () => useSessionStore.getState().token,
  onUnauthorized: () => useSessionStore.getState().clear(),
});
