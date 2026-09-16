import { describe, expect, it } from "vitest";
import pinned from "../../../../deployment/realtime-timeouts.json";
import { backoffDelay, LOAD_BALANCER_IDLE_TIMEOUT_MS, PING_INTERVAL_MS } from "./timeouts";

describe("realtime timeouts", () => {
  it("reads the ping interval from the shared file", () => {
    expect(PING_INTERVAL_MS).toBe(pinned.ping_interval_seconds * 1000);
  });

  it("pings well inside the load balancer idle timeout", () => {
    expect(PING_INTERVAL_MS * 2).toBeLessThanOrEqual(LOAD_BALANCER_IDLE_TIMEOUT_MS);
  });

  it("backs off exponentially with a cap", () => {
    expect(backoffDelay(1)).toBe(1_000);
    expect(backoffDelay(3)).toBe(4_000);
    expect(backoffDelay(10)).toBe(30_000);
  });
});
