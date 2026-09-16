// The one client instance the whole app shares.
import { createClient } from "@tadas/api-client";
import { useSessionStore } from "../store/session";

export const api = createClient({
  baseUrl: import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000",
  app: "portal",
  appVersion: __APP_VERSION__,
  getToken: () => useSessionStore.getState().token,
  onUnauthorized: () => useSessionStore.getState().clear(),
});
