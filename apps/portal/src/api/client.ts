// One transport client: bearer, app header, the error envelope parsed into
// a typed error carrying the request id, a 401 that clears authentication,
// and a deadline on every call. The one file in the app that may call fetch.

export interface ErrorEnvelope {
  error: { code: string; message: string; request_id: string };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

/** A call that did not finish, headers and body, within the client's deadline. */
export class RequestTimeout extends Error {
  readonly method: string;
  readonly path: string;
  readonly timeoutMs: number;

  constructor(method: string, path: string, timeoutMs: number) {
    super(`${method} ${path} did not finish within ${timeoutMs} ms`);
    this.name = "RequestTimeout";
    this.method = method;
    this.path = path;
    this.timeoutMs = timeoutMs;
  }
}

export interface ClientOptions {
  baseUrl: string;
  app: "portal" | "admin" | "cli" | "api";
  appVersion: string;
  /** Every call is abandoned after this many milliseconds; no call goes out without one. */
  timeoutMs: number;
  getToken: () => string | null;
  onUnauthorized: () => void;
  fetchImpl?: typeof fetch;
}

export interface RequestOptions {
  idempotencyKey?: string;
  token?: string | null;
  signal?: AbortSignal;
}

export interface ApiClient {
  readonly baseUrl: string;
  request<T>(method: string, path: string, body?: unknown, options?: RequestOptions): Promise<T>;
  get<T>(path: string, options?: RequestOptions): Promise<T>;
  post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T>;
  patch<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T>;
  del<T>(path: string, options?: RequestOptions): Promise<T>;
  websocketUrl(path: string): string;
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return typeof error === "object" && error !== null && "code" in error && "message" in error;
}

export function createClient(options: ClientOptions): ApiClient {
  const fetchImpl = options.fetchImpl ?? fetch;
  const baseUrl = options.baseUrl.replace(/\/$/, "");

  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    requestOptions: RequestOptions = {},
  ): Promise<T> {
    const headers = new Headers({
      Accept: "application/json",
      "X-App": options.app,
      "X-App-Version": options.appVersion,
    });
    const token = requestOptions.token === undefined ? options.getToken() : requestOptions.token;
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (body !== undefined) headers.set("Content-Type", "application/json");
    if (requestOptions.idempotencyKey) headers.set("Idempotency-Key", requestOptions.idempotencyKey);

    // One signal for the whole call: the deadline, and the caller's own
    // signal when it hands one over. Reading the body counts against the
    // deadline too, so the timer runs until the body is in.
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(new RequestTimeout(method, path, options.timeoutMs)),
      options.timeoutMs,
    );
    const callerSignal = requestOptions.signal;
    const forwardAbort = () => controller.abort(callerSignal?.reason);
    if (callerSignal?.aborted) forwardAbort();
    else callerSignal?.addEventListener("abort", forwardAbort, { once: true });

    let response: Response;
    let text: string;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      text = response.status === 204 ? "" : await response.text();
    } catch (error) {
      // A fetch aborted by the deadline reports the reason it was aborted with.
      throw controller.signal.aborted ? controller.signal.reason : error;
    } finally {
      clearTimeout(timer);
      callerSignal?.removeEventListener("abort", forwardAbort);
    }
    const requestId = response.headers.get("x-request-id");
    if (response.status === 204) return undefined as T;
    const parsed: unknown = text ? JSON.parse(text) : null;
    if (!response.ok) {
      if (response.status === 401) options.onUnauthorized();
      if (isErrorEnvelope(parsed)) {
        throw new ApiError(
          response.status,
          parsed.error.code,
          parsed.error.message,
          parsed.error.request_id ?? requestId,
        );
      }
      throw new ApiError(response.status, "unknown_error", response.statusText, requestId);
    }
    return parsed as T;
  }

  return {
    baseUrl,
    request,
    get: (path, requestOptions) => request("GET", path, undefined, requestOptions),
    post: (path, body, requestOptions) => request("POST", path, body, requestOptions),
    patch: (path, body, requestOptions) => request("PATCH", path, body, requestOptions),
    del: (path, requestOptions) => request("DELETE", path, undefined, requestOptions),
    websocketUrl: (path) => baseUrl.replace(/^http/, "ws") + path,
  };
}
