// One provider owns the socket for the whole app: ticket, connect, subscribe,
// ping, reconnect with backoff, and the degraded polling mode with its banner.
import { useQueryClient } from "@tanstack/react-query";
import type { TicketView } from "@tadas/api-client";
import { useEffect, type ReactNode } from "react";
import { api } from "../app/api";
import { Banner } from "../design/kit";
import { useConnectionStore } from "../store/connection";
import { useSessionStore } from "../store/session";
import { parseEnvelope, type ClientCommand } from "./envelopes";
import { routeEnvelope } from "./router";
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

    const send = (command: ClientCommand) => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(command));
    };

    const stopPolling = () => {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
    };

    const startPolling = () => {
      if (pollTimer) return;
      pollTimer = setInterval(() => void queryClient.invalidateQueries(), DEGRADED_POLL_INTERVAL_MS);
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
      let ticket: TicketView;
      try {
        ticket = await api.post<TicketView>("/v1/realtime/tickets");
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
        void queryClient.invalidateQueries();
        for (const topic of TOPICS) send({ op: "subscribe", topic });
        pingTimer = setInterval(() => send({ op: "ping" }), PING_INTERVAL_MS);
      };
      socket.onmessage = (message) => {
        const envelope = parseEnvelope(String(message.data));
        if (envelope) routeEnvelope(queryClient, envelope);
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
