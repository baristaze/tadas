// The settings a build does not carry. In the cloud the portal's host serves
// /config.json, written per environment (the API is e.g. https://api.tadas.fyi),
// so one build runs anywhere.
// Locally there is none (the dev server and nginx answer with index.html),
// and the Vite build variables apply instead.

export interface RuntimeConfig {
  /** Absolute base URL of the API; an empty value in the file means the page's origin. */
  apiUrl: string;
  sentryDsn: string;
  environment: string;
}

export interface BuildEnv {
  VITE_API_URL?: string;
  VITE_SENTRY_DSN?: string;
  VITE_SENTRY_ENVIRONMENT?: string;
}

const LOCAL_API = "http://127.0.0.1:8000";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Pure: the fetched config if it is one, else the build variables. An empty
 * apiUrl means the API shares the page's origin. */
export function resolveConfig(fetched: unknown, env: BuildEnv, origin: string): RuntimeConfig {
  if (isRecord(fetched) && typeof fetched.apiUrl === "string") {
    return {
      apiUrl: fetched.apiUrl || origin,
      sentryDsn: typeof fetched.sentryDsn === "string" ? fetched.sentryDsn : "",
      environment: typeof fetched.environment === "string" ? fetched.environment : "unknown",
    };
  }
  return {
    apiUrl: env.VITE_API_URL || LOCAL_API,
    sentryDsn: env.VITE_SENTRY_DSN ?? "",
    environment: env.VITE_SENTRY_ENVIRONMENT ?? "local",
  };
}

let current: RuntimeConfig | null = null;

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  let fetched: unknown = null;
  try {
    // A static file of the page's own origin, not an API call.
    // eslint-disable-next-line no-restricted-globals
    const response = await fetch("/config.json", { cache: "no-store" });
    if (response.ok && response.headers.get("content-type")?.includes("json")) {
      fetched = await response.json();
    }
  } catch {
    // No config file: the build variables apply.
  }
  current = resolveConfig(fetched, import.meta.env, window.location.origin);
  return current;
}

export function runtimeConfig(): RuntimeConfig {
  if (current === null) throw new Error("runtime config read before loadRuntimeConfig()");
  return current;
}
