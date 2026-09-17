import * as Sentry from "@sentry/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { loadRuntimeConfig } from "./app/config";
import { initErrorReporting } from "./app/errors";
import "./design/motion.css";

// The config comes first: the API client and error reporting are built from it,
// so the app is imported only once it is known.
const config = await loadRuntimeConfig();
initErrorReporting(config);
const { App } = await import("./app/App");

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
