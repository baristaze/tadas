import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { parseEnvelope } from "./envelopes";
import { routeEnvelope } from "./router";

describe("routeEnvelope", () => {
  it("invalidates queries by the entity name in the push", () => {
    const queryClient = new QueryClient();
    const seen: unknown[] = [];
    queryClient.invalidateQueries = (filters) => {
      seen.push(filters);
      return Promise.resolve();
    };
    const envelope = parseEnvelope(
      JSON.stringify({
        type: "event",
        seq: 3,
        sent_at: null,
        topic: "entity_changed",
        payload: { entity: "api_key", entity_id: "x", action: "created" },
      }),
    );
    expect(envelope).not.toBeNull();
    expect(routeEnvelope(queryClient, envelope!)).toEqual({ invalidated: ["api_key"] });
    expect(seen).toEqual([{ queryKey: ["api_key"] }]);
  });

  it("ignores frames that are not pushes and rejects malformed ones", () => {
    const queryClient = new QueryClient();
    const pong = parseEnvelope(JSON.stringify({ type: "pong", seq: 1, sent_at: null }));
    expect(routeEnvelope(queryClient, pong!)).toEqual({ invalidated: [] });
    expect(parseEnvelope("not json")).toBeNull();
    expect(parseEnvelope(JSON.stringify({ type: "mystery", seq: 1 }))).toBeNull();
  });
});
