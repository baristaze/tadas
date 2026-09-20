// The one query cache the whole app shares. It lives outside the component
// tree so that forgetting a session can empty it from anywhere.
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: 1 } },
});
