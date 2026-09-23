// The one query cache the whole app shares. It lives outside the component
// tree so that forgetting a session can empty it from anywhere.
import { MutationCache, QueryClient } from "@tanstack/react-query";
import { offerUpgrade } from "../store/upgrade";

// No retry here. The app's one retry is in the transport client
// (src/api/client.ts), which knows the method, the idempotency key, and the
// failure, and a retry above one that already ran would multiply the calls a
// failing API sees. Mutations are the same rule said twice, since a write
// this layer repeated would not carry the key that makes it safe.
//
// Every write passes the mutation cache, so it is the one place a refusal for
// a plan's bound is turned into the upgrade dialog: a view-model that says a
// failure itself skips this one (`isPlanLimit`), and the person sees the
// plans, not a notice.
export const queryClient = new QueryClient({
  mutationCache: new MutationCache({ onError: (error) => void offerUpgrade(error) }),
  defaultOptions: {
    queries: { staleTime: 10_000, retry: false },
    mutations: { retry: false },
  },
});
