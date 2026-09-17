import * as Sentry from "@sentry/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { initErrorReporting } from "./app/errors";

initErrorReporting();

const root = document.getElementById("root");
if (root === null) throw new Error("index.html has no #root");
createRoot(root, {
  // React 19 hands uncaught and recoverable render errors to these hooks.
  onUncaughtError: Sentry.reactErrorHandler(),
  onRecoverableError: Sentry.reactErrorHandler(),
}).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
