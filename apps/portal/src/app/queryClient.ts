// The one query cache the whole app shares. It lives outside the component
// tree so that forgetting a session can empty it from anywhere.
import { QueryClient } from "@tanstack/react-query";

// No retry here. The app's one retry is in the transport client
// (src/api/client.ts), which knows the method, the idempotency key, and the
// failure, and a retry above one that already ran would multiply the calls a
// failing API sees. Mutations are the same rule said twice, since a write
// this layer repeated would not carry the key that makes it safe.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: false },
    mutations: { retry: false },
  },
});
