// The discriminated union on `type`, hand-written to mirror the service's
// realtime envelopes. Commands travel the other way, and they are small.

interface Base {
  sent_at: string | null;
}

export interface HelloEnvelope extends Base {
  type: "hello";
  org_id: string;
  user_id: string;
  ping_interval_seconds: number;
}

export interface PongEnvelope extends Base {
  type: "pong";
}

export interface SubscribedEnvelope extends Base {
  type: "subscribed";
  topic: string;
}

export interface UnsubscribedEnvelope extends Base {
  type: "unsubscribed";
  topic: string;
}

// Mirrors the service's EntityChangedView: which record changed (`kind` is
// "<namespace>.<entity>.<action>") and where it sits in the tenant's stream.
// Every push has a record, so `seq` is always a number. Read tolerantly: a
// field the client does not know is ignored.
export interface EntityChangedView {
  kind: string;
  target_id: string;
  seq: number;
}

// The entity name inside a kind, which is what query keys start with.
export function entityOf(kind: string): string {
  const parts = kind.split(".");
  return parts.length >= 2 ? parts[1]! : kind;
}

export interface EventEnvelope extends Base {
  type: "event";
  topic: string;
  payload: EntityChangedView;
}

export interface ErrorEnvelope extends Base {
  type: "error";
  code: string;
  message: string;
}

export type Envelope =
  | HelloEnvelope
  | PongEnvelope
  | SubscribedEnvelope
  | UnsubscribedEnvelope
  | EventEnvelope
  | ErrorEnvelope;

export type ClientCommand =
  | { op: "subscribe"; topic: string }
  | { op: "unsubscribe"; topic: string }
  | { op: "ping" };

const TYPES = new Set(["hello", "pong", "subscribed", "unsubscribed", "event", "error"]);

export function parseEnvelope(raw: string): Envelope | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const candidate = parsed as { type?: unknown };
  if (typeof candidate.type !== "string" || !TYPES.has(candidate.type)) return null;
  return parsed as Envelope;
}

export function isEntityChanged(envelope: Envelope): envelope is EventEnvelope {
  if (envelope.type !== "event" || envelope.topic !== "entity_changed") return false;
  const payload: unknown = envelope.payload;
  if (typeof payload !== "object" || payload === null) return false;
  const view = payload as Partial<EntityChangedView>;
  return (
    typeof view.kind === "string" && typeof view.target_id === "string" && typeof view.seq === "number"
  );
}
