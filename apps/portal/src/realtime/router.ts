// Envelopes route into the query cache, never into components. An
// `entity_changed` push invalidates every query whose key starts with the
// entity name inside the kind; the key factory spells keys that way on purpose.
import type { QueryClient } from "@tanstack/react-query";
import { entityOf, isEntityChanged, type Envelope } from "./envelopes";

export interface RouteOutcome {
  invalidated: string[];
}

export function routeEnvelope(queryClient: QueryClient, envelope: Envelope): RouteOutcome {
  if (isEntityChanged(envelope)) {
    const entity = entityOf(envelope.payload.kind);
    void queryClient.invalidateQueries({ queryKey: [entity] });
    return { invalidated: [entity] };
  }
  return { invalidated: [] };
}
