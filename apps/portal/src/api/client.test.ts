import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createClient, RequestTimeout, type ClientOptions } from "./client";

// A fetch that never answers on its own and rejects with the signal's reason
// once it is aborted, or at once when it already is, the way a real fetch does.
function hangingFetch(): typeof fetch {
  return (_input, init) =>
    new Promise((_, reject) => {
      const signal = init?.signal;
      if (signal?.aborted) reject(signal.reason);
      signal?.addEventListener("abort", () => reject(signal.reason));
    });
}

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function client(overrides: Partial<ClientOptions> = {}) {
  return createClient({
    baseUrl: "https://api.example.test/",
    app: "portal",
    appVersion: "portal@test",
    timeoutMs: 20,
    getToken: () => "tok_1",
    onUnauthorized: () => undefined,
    ...overrides,
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("transport client deadline", () => {
  it("rejects a call whose response never arrives once the timeout passes", async () => {
    const api = client({ fetchImpl: hangingFetch() });
    const started = Date.now();
    const failure = await api.get("/v1/tasks").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(RequestTimeout);
    expect(failure).toMatchObject({ method: "GET", path: "/v1/tasks", timeoutMs: 20 });
    expect(Date.now() - started).toBeGreaterThanOrEqual(15);
  });

  it("counts reading the body against the same deadline", async () => {
    const fetchImpl: typeof fetch = (_input, init) =>
      Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers(),
        text: () =>
          new Promise<string>((_, reject) => {
            init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
          }),
      } as unknown as Response);
    const failure = await client({ fetchImpl }).get("/v1/tasks").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(RequestTimeout);
  });

  it("hands every call a signal, and drops the timer once the call is done", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(200, { id: "t1" })));
    const api = client({ fetchImpl, timeoutMs: 30_000 });
    await expect(api.get("/v1/tasks/t1")).resolves.toEqual({ id: "t1" });
    const init = fetchImpl.mock.calls[0]?.[1];
    expect(init?.signal).toBeInstanceOf(AbortSignal);
    expect(init?.signal?.aborted).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps the caller's own abort, which is not a timeout", async () => {
    const api = client({ fetchImpl: hangingFetch(), timeoutMs: 30_000 });
    const controller = new AbortController();
    const pending = api.get("/v1/tasks", { signal: controller.signal }).catch((error: unknown) => error);
    controller.abort(new Error("navigated away"));
    const failure = await pending;
    expect(failure).toBeInstanceOf(Error);
    expect(failure).not.toBeInstanceOf(RequestTimeout);
    expect((failure as Error).message).toBe("navigated away");
  });

  it("refuses at once a call whose signal is already aborted", async () => {
    const fetchImpl = vi.fn<typeof fetch>(hangingFetch());
    const controller = new AbortController();
    controller.abort(new Error("already gone"));
    const failure = await client({ fetchImpl })
      .get("/v1/tasks", { signal: controller.signal })
      .catch((error: unknown) => error);
    expect((failure as Error).message).toBe("already gone");
  });

  it("still parses the error envelope into a typed error", async () => {
    const fetchImpl: typeof fetch = () =>
      Promise.resolve(
        jsonResponse(404, { error: { code: "not_found", message: "no such task", request_id: "req_1" } }),
      );
    const failure = await client({ fetchImpl }).get("/v1/tasks/x").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 404, code: "not_found", requestId: "req_1" });
  });
});
