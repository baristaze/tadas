// The portal is a consumer of the pin: the file is read from disk here, apart
// from the module's own import, so a value the module carries that is not the
// one deployment pinned fails this test.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { backoffDelay, LOAD_BALANCER_IDLE_TIMEOUT_MS, PING_INTERVAL_MS } from "./timeouts";

const PINNED_FILE = new URL("../../../../deployment/realtime-timeouts.json", import.meta.url);

interface Pinned {
  ping_interval_seconds: number;
  server_ping_interval_seconds: number;
  server_ping_timeout_seconds: number;
  load_balancer_idle_timeout_seconds: number;
}

function pinned(): Pinned {
  const parsed: unknown = JSON.parse(readFileSync(PINNED_FILE, "utf8"));
  expect(parsed).toMatchObject({
    ping_interval_seconds: expect.any(Number),
    server_ping_interval_seconds: expect.any(Number),
    server_ping_timeout_seconds: expect.any(Number),
    load_balancer_idle_timeout_seconds: expect.any(Number),
  });
  return parsed as Pinned;
}

describe("realtime timeouts", () => {
  it("carries the ping interval and the idle timeout the deployment pinned", () => {
    const pin = pinned();
    expect(PING_INTERVAL_MS).toBe(pin.ping_interval_seconds * 1000);
    expect(LOAD_BALANCER_IDLE_TIMEOUT_MS).toBe(pin.load_balancer_idle_timeout_seconds * 1000);
  });

  it("pings well inside the load balancer idle timeout", () => {
    const pin = pinned();
    expect(pin.ping_interval_seconds * 2).toBeLessThanOrEqual(pin.load_balancer_idle_timeout_seconds);
    expect(PING_INTERVAL_MS * 2).toBeLessThanOrEqual(LOAD_BALANCER_IDLE_TIMEOUT_MS);
  });

  it("leaves the server's ping and its timeout inside the idle timeout too", () => {
    // The server ends a dead socket before the load balancer would: the
    // protocol ping it sends, plus the wait for the pong, fits the idle timeout.
    const pin = pinned();
    expect(pin.server_ping_interval_seconds + pin.server_ping_timeout_seconds).toBeLessThan(
      pin.load_balancer_idle_timeout_seconds,
    );
  });

  it("backs off exponentially with a cap", () => {
    expect(backoffDelay(1)).toBe(1_000);
    expect(backoffDelay(3)).toBe(4_000);
    expect(backoffDelay(10)).toBe(30_000);
  });
});
