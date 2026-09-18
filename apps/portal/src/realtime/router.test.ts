import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { parseEnvelope } from "./envelopes";
import { routeEnvelope } from "./router";

describe("routeEnvelope", () => {
  it("invalidates queries by the entity name inside the push's kind, ignoring unknown fields", () => {
    const queryClient = new QueryClient();
    const seen: unknown[] = [];
    queryClient.invalidateQueries = (filters) => {
      seen.push(filters);
      return Promise.resolve();
    };
    const envelope = parseEnvelope(
      JSON.stringify({
        type: "event",
        sent_at: null,
        topic: "entity_changed",
        payload: { kind: "tenancy.api_key.created", target_id: "x", seq: 3, added_later: 1 },
      }),
    );
    expect(envelope).not.toBeNull();
    expect(routeEnvelope(queryClient, envelope!)).toEqual({ invalidated: ["api_key"] });
    expect(seen).toEqual([{ queryKey: ["api_key"] }]);
  });

  it("ignores frames that are not pushes and rejects malformed ones", () => {
    const queryClient = new QueryClient();
    const pong = parseEnvelope(JSON.stringify({ type: "pong", sent_at: null }));
    expect(routeEnvelope(queryClient, pong!)).toEqual({ invalidated: [] });
    expect(parseEnvelope("not json")).toBeNull();
    expect(parseEnvelope(JSON.stringify({ type: "mystery" }))).toBeNull();
    const bare = parseEnvelope(
      JSON.stringify({ type: "event", sent_at: null, topic: "entity_changed", payload: {} }),
    );
    expect(routeEnvelope(queryClient, bare!)).toEqual({ invalidated: [] });
  });
});
