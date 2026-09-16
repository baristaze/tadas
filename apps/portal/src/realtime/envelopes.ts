// The discriminated union on `type`, hand-written to mirror the service's
// realtime envelopes. Commands travel the other way, and they are small.

interface Base {
  seq: number;
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

export interface EntityChangedPayload {
  idempotency_key: string;
  produced_at: string;
  org_id: string;
  entity: string;
  entity_id: string;
  action: "created" | "updated" | "deleted";
}

export interface EventEnvelope extends Base {
  type: "event";
  topic: string;
  payload: Record<string, unknown>;
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
  const candidate = parsed as { type?: unknown; seq?: unknown };
  if (typeof candidate.type !== "string" || !TYPES.has(candidate.type)) return null;
  if (typeof candidate.seq !== "number") return null;
  return parsed as Envelope;
}

export function isEntityChanged(envelope: EventEnvelope): envelope is EventEnvelope & {
  payload: EntityChangedPayload;
} {
  const payload = envelope.payload;
  return (
    envelope.topic === "entity_changed" &&
    typeof payload.entity === "string" &&
    typeof payload.entity_id === "string"
  );
}
