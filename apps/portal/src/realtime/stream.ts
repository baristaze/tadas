// Pure: where a push sits relative to the last stream position the client
// saw, and how a replayed record becomes the envelope it would have been.
// The socket is a hint; the stream in storage is the truth, so a gap is
// closed by fetching after the cursor rather than by trusting the frame.
import type { EventView } from "@tadas/api-client";
import type { EventEnvelope } from "./envelopes";

// The last seq the client applied; null until the first sequenced push.
export type Cursor = number | null;

export type Placement =
  | { kind: "next"; cursor: number } // in order: route it and advance
  | { kind: "unsequenced" } // no stream position: route it, keep the cursor
  | { kind: "seen" } // at or behind the cursor: already applied, drop it
  | { kind: "gap"; after: number }; // ahead of the cursor: replay after it first

export function place(cursor: Cursor, seq: number | null): Placement {
  if (seq === null) return { kind: "unsequenced" };
  if (cursor === null) return { kind: "next", cursor: seq };
  if (seq <= cursor) return { kind: "seen" };
  if (seq === cursor + 1) return { kind: "next", cursor: seq };
  return { kind: "gap", after: cursor };
}

export function eventEnvelope(event: EventView): EventEnvelope {
  return {
    type: "event",
    topic: "entity_changed",
    sent_at: null,
    payload: {
      entity: event.entity,
      entity_id: event.entity_id,
      action: event.action as EventEnvelope["payload"]["action"],
      seq: event.seq,
    },
  };
}

// A page shorter than the limit is the last one.
export function isLastPage(received: number, limit: number): boolean {
  return received < limit;
}
