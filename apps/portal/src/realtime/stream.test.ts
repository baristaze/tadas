import type { EventView } from "../api";
import { describe, expect, it } from "vitest";
import { eventEnvelope, isLastPage, place } from "./stream";

describe("place", () => {
  it("takes the first sequenced push as the cursor", () => {
    expect(place(null, 7)).toEqual({ kind: "next", cursor: 7 });
  });

  it("advances on the next seq and drops what was already applied", () => {
    expect(place(7, 8)).toEqual({ kind: "next", cursor: 8 });
    expect(place(7, 7)).toEqual({ kind: "seen" });
    expect(place(7, 3)).toEqual({ kind: "seen" });
  });

  it("names the replay point when a seq is skipped", () => {
    expect(place(7, 9)).toEqual({ kind: "gap", after: 7 });
    expect(place(7, 100)).toEqual({ kind: "gap", after: 7 });
  });

});

describe("eventEnvelope", () => {
  it("turns a replayed record into the envelope the socket would have carried", () => {
    const event: EventView = {
      seq: 4,
      kind: "tasks.task.updated",
      target_id: "t1",
      produced_at: "2026-09-16T12:00:00Z",
    };
    expect(eventEnvelope(event)).toEqual({
      type: "event",
      topic: "entity_changed",
      sent_at: null,
      payload: { kind: "tasks.task.updated", target_id: "t1", seq: 4 },
    });
  });

  it("ends paging on a short page", () => {
    expect(isLastPage(200, 200)).toBe(false);
    expect(isLastPage(199, 200)).toBe(true);
    expect(isLastPage(0, 200)).toBe(true);
  });
});
