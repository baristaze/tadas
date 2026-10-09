// Envelopes route into the query cache, never into components. An
// `entity_changed` push names an entity inside its kind
// (`<namespace>.<entity>.<action>`) and one record of it. For an entity with
// a hint reader, the push is a hint: the reader reads that one record and
// places it (`hints.ts`). Any other push invalidates the queries that carry
// its entity: by convention the queries whose key starts with the entity
// name, and by the table below where the entity is read through another
// query, or through none.
import type { QueryClient, QueryKey } from "@tanstack/react-query";
import { keys } from "../queries/keys";
import { entityOf, isEntityChanged, type Envelope, type EventEnvelope } from "./envelopes";
import type { Hints } from "./hints";

export interface RouteOutcome {
  invalidated: QueryKey[];
  /** The entity whose reader took the push as a hint, when one did. */
  hinted?: string;
}

/** The hint reader of each entity read one record at a time. */
export type HintReaders = Readonly<Record<string, Hints>>;

// Entities the convention does not reach on its own. A membership is read as
// the role and the permissions inside `me`, as the role in the person's list
// of places the org chip reads, and as the role beside each member in
// Settings; a user is read twice, as a row of the member list and as the name
// and the email in `me`, so a user push reaches both: its reader places the
// member in both (`userCache.ts`). A task push is read the same way: its
// reader places the task in every list (`taskCache.ts`). A revoked session is
// nobody's query: this session's own revocation arrives as a 4401 close, not
// as a push. A billing account is read as the org's plan, with the seats and
// the active tasks beside it. An orchestration's record is an import's, read
// under its own entity (`keys.imports`).
const CARRIED_BY: Readonly<Record<string, readonly QueryKey[]>> = {
  account: [keys.billing],
  membership: [keys.me, keys.myMemberships.all, keys.memberships.all],
  user: [keys.users.all, keys.me],
  session: [],
};

function targetsOf(entity: string): readonly QueryKey[] {
  return CARRIED_BY[entity] ?? [[entity]];
}

// Every entity the server pushes on the channel. The router test holds it to
// the kinds the service sends.
export const PUSHED_ENTITIES = [
  "account",
  "api_key",
  "file",
  "installation",
  "invitation",
  "membership",
  "orchestration",
  "session",
  "task",
  "user",
] as const;

const KEPT_FRESH = new Set(PUSHED_ENTITIES.flatMap((entity) => targetsOf(entity).map((key) => key[0])));

/** Whether a push reaches the query under this key: its first element is a
 * pushed entity, or a key the table above names. While the socket is open
 * such a query is as fresh as the last push, so it is not read again on its
 * own (`queryClient.ts`). A query no push names (the person's identity, a
 * file's signed preview) is not. */
export function isKeptFresh(queryKey: QueryKey): boolean {
  return KEPT_FRESH.has(queryKey[0] as string);
}

/** Routes one envelope, live or read back from the stream: the entity's
 * reader reads the one record it names, or, for an entity with none, every
 * query the entity is read from is read again. */
export function routeEnvelope(
  queryClient: QueryClient,
  envelope: Envelope,
  readers: HintReaders = {},
): RouteOutcome {
  if (!isEntityChanged(envelope)) return { invalidated: [] };
  const entity = entityOf(envelope.payload.kind);
  const reader = readers[entity];
  if (reader) {
    const { target_id: id, version } = envelope.payload;
    reader.hint(id, typeof version === "number" ? version : undefined);
    return { invalidated: [], hinted: entity };
  }
  const targets = [...targetsOf(entity)];
  for (const queryKey of targets) void queryClient.invalidateQueries({ queryKey });
  return { invalidated: targets };
}

/** What a page read back from the stream keeps one push of, the last: the
 * record, for an entity whose reader reads each record, and the entity for
 * any other, since one invalidation reads all of it again. */
export function replayKey(envelope: EventEnvelope, readers: HintReaders = {}): string {
  const entity = entityOf(envelope.payload.kind);
  return readers[entity] ? `${entity}/${envelope.payload.target_id}` : entity;
}

// A reminder is the one push a person is told about as well as refreshed by:
// the task is read and placed as above, and this names the task to announce.
// Null for every other frame.
export const REMINDED_KIND = "tasks.task.reminded";

export function reminderOf(envelope: Envelope): string | null {
  if (!isEntityChanged(envelope) || envelope.payload.kind !== REMINDED_KIND) return null;
  return envelope.payload.target_id;
}
