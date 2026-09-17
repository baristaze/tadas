// Error reporting to a Sentry-compatible backend (GlitchTip locally). It is on
// only when VITE_SENTRY_DSN is compiled in; without it every call is a no-op.
import * as Sentry from "@sentry/react";

export function initErrorReporting(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;
  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT ?? "local",
    release: __APP_VERSION__,
    sendDefaultPii: false,
  });
}

export function reportError(error: unknown): void {
  Sentry.captureException(error);
}
