import { describe, expect, it } from "vitest";
import { DEFAULT_REQUEST_TIMEOUT_MS, resolveConfig } from "./config";

const origin = "https://d111.cloudfront.net";

describe("runtime config", () => {
  it("uses the fetched config, with an empty apiUrl meaning the page's origin", () => {
    expect(resolveConfig({ apiUrl: "", sentryDsn: "https://k@s/1", environment: "dev" }, {}, origin)).toEqual({
      apiUrl: origin,
      sentryDsn: "https://k@s/1",
      environment: "dev",
      requestTimeoutMs: DEFAULT_REQUEST_TIMEOUT_MS,
    });
    expect(resolveConfig({ apiUrl: "https://api.example.test" }, {}, origin)).toEqual({
      apiUrl: "https://api.example.test",
      sentryDsn: "",
      environment: "unknown",
      requestTimeoutMs: DEFAULT_REQUEST_TIMEOUT_MS,
    });
  });

  it("takes the request timeout from the config when it is a positive number", () => {
    expect(resolveConfig({ apiUrl: "", requestTimeoutMs: 5_000 }, {}, origin).requestTimeoutMs).toBe(5_000);
    for (const notATimeout of [0, -1, "5000", null, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(resolveConfig({ apiUrl: "", requestTimeoutMs: notATimeout }, {}, origin).requestTimeoutMs).toBe(
        DEFAULT_REQUEST_TIMEOUT_MS,
      );
    }
  });

  it("falls back to the build variables when there is no config file", () => {
    const env = { VITE_API_URL: "http://127.0.0.1:8000", VITE_SENTRY_DSN: "http://k@localhost:58000/1" };
    for (const notAConfig of [null, "<!doctype html>", [], { apiUrl: 42 }]) {
      expect(resolveConfig(notAConfig, env, origin)).toEqual({
        apiUrl: "http://127.0.0.1:8000",
        sentryDsn: "http://k@localhost:58000/1",
        environment: "local",
        requestTimeoutMs: DEFAULT_REQUEST_TIMEOUT_MS,
      });
    }
    expect(resolveConfig(null, {}, origin).apiUrl).toBe("http://127.0.0.1:8000");
  });
});
