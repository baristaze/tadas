// Envelopes route into the query cache, never into components. An
// `entity_changed` push invalidates the queries that carry the entity named
// inside its kind: by convention the queries whose key starts with the entity
// name, and by the table below where the entity is read through another
// query, or through none.
import type { QueryClient, QueryKey } from "@tanstack/react-query";
import { keys } from "../queries/keys";
import { entityOf, isEntityChanged, type Envelope } from "./envelopes";

export interface RouteOutcome {
  invalidated: QueryKey[];
}

// Entities the convention does not reach on its own. A membership is read as
// the role and the permissions inside `me`; a user is read twice, as a row of
// the member list and as the name and the email in `me`, so a user push
// refreshes both; a revoked session is nobody's query, and this session's own
// revocation arrives as a 4401 close, not as a push.
const CARRIED_BY: Readonly<Record<string, readonly QueryKey[]>> = {
  membership: [keys.me],
  user: [keys.users.all, keys.me],
  session: [],
};

function targetsOf(entity: string): readonly QueryKey[] {
  return CARRIED_BY[entity] ?? [[entity]];
}

export function routeEnvelope(queryClient: QueryClient, envelope: Envelope): RouteOutcome {
  if (!isEntityChanged(envelope)) return { invalidated: [] };
  const targets = [...targetsOf(entityOf(envelope.payload.kind))];
  for (const queryKey of targets) void queryClient.invalidateQueries({ queryKey });
  return { invalidated: targets };
}
