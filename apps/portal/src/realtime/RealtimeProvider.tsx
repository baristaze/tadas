// One provider owns the socket for the whole app: ticket, connect, subscribe,
// ping, reconnect with backoff, and the degraded polling mode with its banner.
// It remembers the last stream position it applied; a reconnect or a gap is
// closed by replaying /v1/events after it through the same envelope router.
import { useQueryClient } from "@tanstack/react-query";
import type { IssuedTicketView } from "../api";
import { useEffect, type ReactNode } from "react";
import { api } from "../app/api";
import { Banner } from "../design/kit";
import { EVENTS_PAGE, fetchEventsAfter } from "../queries/events";
import { useConnectionStore } from "../store/connection";
import { useSessionStore } from "../store/session";
import { isEntityChanged, parseEnvelope, type ClientCommand, type Envelope } from "./envelopes";
import { routeEnvelope } from "./router";
import { behind, eventEnvelope, isLastPage, place, type Cursor } from "./stream";
import { backoffDelay, DEGRADED_POLL_INTERVAL_MS, PING_INTERVAL_MS } from "./timeouts";

const TOPICS = ["entity_changed"];

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const token = useSessionStore((s) => s.token);
  const status = useConnectionStore((s) => s.status);

  useEffect(() => {
    if (!token) return;
    const connection = useConnectionStore.getState();
    let socket: WebSocket | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let stopped = false;
    let cursor: Cursor = null;
    // Frames and replays are applied strictly in arrival order.
    let inbox: Promise<void> = Promise.resolve();

    const send = (command: ClientCommand) => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(command));
    };

    // Routes one envelope unless it is behind the cursor; returns the seq to
    // replay after when the envelope is ahead of it.
    const apply = (envelope: Envelope): number | null => {
      if (!isEntityChanged(envelope)) {
        routeEnvelope(queryClient, envelope);
        return null;
      }
      const placement = place(cursor, envelope.payload.seq);
      if (placement.kind === "seen") return null;
      if (placement.kind === "gap") return placement.after;
      routeEnvelope(queryClient, envelope);
      if (placement.kind === "next") cursor = placement.cursor;
      return null;
    };

    // Pages through the stream after `after`, applying each record through
    // the router; false when the fetch failed and the cursor stayed put.
    const replay = async (after: number): Promise<boolean> => {
      let from = after;
      for (;;) {
        let page;
        try {
          page = await fetchEventsAfter(from, EVENTS_PAGE);
        } catch {
          return false;
        }
        for (const event of page) apply(eventEnvelope(event));
        if (isLastPage(page.length, EVENTS_PAGE)) return true;
        from = cursor ?? from;
      }
    };

    const deliver = async (envelope: Envelope) => {
      // A pong names the head; a head past the cursor is a gap no frame announced.
      if (envelope.type === "pong") {
        const after = behind(cursor, envelope.seq);
        if (after !== null) await replay(after);
        return;
      }
      const gap = apply(envelope);
      if (gap === null) return;
      const replayed = await replay(gap);
      if (apply(envelope) === null) return;
      // Still out of order: the push is worth routing either way. After a
      // failed replay the cursor stays so the next push retries the fetch.
      routeEnvelope(queryClient, envelope);
      if (replayed && isEntityChanged(envelope)) {
        cursor = envelope.payload.seq;
      }
    };

    const enqueue = (work: () => Promise<void>) => {
      inbox = inbox.then(work).catch(() => undefined);
    };

    // What a reconnect and a degraded poll both do: catch up from the cursor.
    // Before the first sequenced push there is no cursor to replay from, so
    // the one time that happens the cache is refreshed wholesale.
    const catchUp = async () => {
      if (cursor === null) {
        await queryClient.invalidateQueries();
        return;
      }
      await replay(cursor);
    };

    const stopPolling = () => {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
    };

    const startPolling = () => {
      if (pollTimer) return;
      pollTimer = setInterval(() => enqueue(catchUp), DEGRADED_POLL_INTERVAL_MS);
    };

    const scheduleReconnect = () => {
      if (stopped) return;
      attempt += 1;
      connection.recordFailure();
      if (useConnectionStore.getState().failedCycles > 1) {
        connection.setStatus("degraded");
        startPolling();
      }
      reconnectTimer = setTimeout(() => void connect(), backoffDelay(attempt));
    };

    const connect = async () => {
      if (stopped) return;
      connection.setStatus(attempt === 0 ? "connecting" : useConnectionStore.getState().status);
      let ticket: IssuedTicketView;
      try {
        ticket = await api.post<IssuedTicketView>("/v1/realtime/tickets");
      } catch {
        scheduleReconnect();
        return;
      }
      if (stopped) return;
      socket = new WebSocket(api.websocketUrl(`/v1/realtime?ticket=${encodeURIComponent(ticket.ticket)}`));
      socket.onopen = () => {
        attempt = 0;
        connection.reset();
        stopPolling();
        for (const topic of TOPICS) send({ op: "subscribe", topic });
        enqueue(catchUp);
        pingTimer = setInterval(() => send({ op: "ping" }), PING_INTERVAL_MS);
      };
      socket.onmessage = (message) => {
        const envelope = parseEnvelope(String(message.data));
        if (!envelope) return;
        // The hello names the stream position, so a reconnect before the
        // first push replays from it instead of refreshing wholesale.
        if (envelope.type === "hello" && cursor === null) cursor = envelope.seq;
        enqueue(() => deliver(envelope));
      };
      socket.onclose = () => {
        if (pingTimer) clearInterval(pingTimer);
        pingTimer = null;
        socket = null;
        if (!stopped) scheduleReconnect();
      };
      socket.onerror = () => socket?.close();
    };

    void connect();
    return () => {
      stopped = true;
      if (pingTimer) clearInterval(pingTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      stopPolling();
      socket?.close();
      connection.setStatus("closed");
    };
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
