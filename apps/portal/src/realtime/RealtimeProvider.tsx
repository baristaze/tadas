// One provider owns the socket for the whole app; the loop itself lives in
// channel.ts, without React, and this component gives it the query cache, the
// transport client, and the connection store, and shows the degraded banner.
import { useQueryClient } from "@tanstack/react-query";
import type { IssuedTicketView } from "../api";
import { useEffect, type ReactNode } from "react";
import { api } from "../app/api";
import { forgetSession } from "../app/forgetSession";
import { Banner } from "../design/kit";
import { EVENTS_PAGE, fetchEventsAfter } from "../queries/events";
import { useConnectionStore } from "../store/connection";
import { useSessionStore } from "../store/session";
import { openChannel } from "./channel";
import { routeEnvelope } from "./router";

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const token = useSessionStore((s) => s.token);
  const status = useConnectionStore((s) => s.status);

  useEffect(() => {
    if (!token) return;
    const channel = openChannel({
      requestTicket: async () => (await api.post<IssuedTicketView>("/v1/realtime/tickets")).ticket,
      openSocket: (ticket) =>
        new WebSocket(api.websocketUrl(`/v1/realtime?ticket=${encodeURIComponent(ticket)}`)),
      fetchEventsAfter,
      route: (envelope) => routeEnvelope(queryClient, envelope),
      refreshAll: () => queryClient.invalidateQueries(),
      connection: useConnectionStore,
      pageSize: EVENTS_PAGE,
      onUnauthenticated: forgetSession,
    });
    return () => channel.stop();
  }, [token, queryClient]);

  return (
    <>
      {status === "degraded" ? (
        <Banner>Live updates are unavailable; refreshing every 30 seconds until they return.</Banner>
      ) : null}
      {children}
    </>
  );
}
