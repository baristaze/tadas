// Pure: where a push sits relative to the last stream position the client
// saw, and how a replayed record becomes the envelope it would have been.
// The socket is a hint; the stream in storage is the truth, so a gap is
// closed by fetching after the cursor rather than by trusting the frame.
import type { EventView } from "../api";
import type { EventEnvelope } from "./envelopes";

// The last contiguous seq the client applied; null until the first push.
export type Cursor = number | null;

export type Placement =
  | { kind: "next"; cursor: number } // in order: route it and advance
  | { kind: "seen" } // at or behind the cursor: already applied, drop it
  | { kind: "gap"; after: number }; // ahead of the cursor: replay after it first, never skip

export function place(cursor: Cursor, seq: number): Placement {
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
      kind: event.kind,
      target_id: event.target_id,
      seq: event.seq,
      actor_id: event.actor_id,
    },
  };
}

// A page shorter than the limit is the last one.
export function isLastPage(received: number, limit: number): boolean {
  return received < limit;
}
