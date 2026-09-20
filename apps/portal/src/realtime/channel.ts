// The socket's whole life without React: ticket, connect, subscribe, ping,
// reconnect with backoff, the degraded polling mode, and the stream cursor.
// Everything it reaches for is handed in, so the loop runs in a test over a
// fake socket and fake timers. The provider owns one of these per session.
import type { EventView } from "../api";
import type { ConnectionState } from "../store/connection";
import { isEntityChanged, parseEnvelope, type ClientCommand, type Envelope } from "./envelopes";
import { behind, eventEnvelope, isLastPage, place, type Cursor } from "./stream";
import { backoffDelay, DEGRADED_POLL_INTERVAL_MS, PING_INTERVAL_MS, STABLE_OPEN_MS } from "./timeouts";

const TOPICS = ["entity_changed"];

/** WebSocket.OPEN, named here so the loop needs no global to compare against. */
export const SOCKET_OPEN = 1;

/** What the loop asks of a socket; a browser WebSocket satisfies it. */
export interface SocketLike {
  readyState: number;
  send(data: string): void;
  close(): void;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
}

export interface ChannelDeps {
  requestTicket(): Promise<string>;
  openSocket(ticket: string): SocketLike;
  fetchEventsAfter(after: number, limit: number): Promise<EventView[]>;
  /** Hands one envelope to the router; the query cache is behind it. */
  route(envelope: Envelope): void;
  /** Refreshes every query, for the one catch-up that has no cursor yet. */
  refreshAll(): Promise<unknown>;
  connection: { getState(): ConnectionState };
  /** Records per replay page; the production size is EVENTS_PAGE. */
  pageSize: number;
}

export interface Channel {
  stop(): void;
  /** The last contiguous seq applied; for tests and the degraded banner. */
  cursor(): Cursor;
}

export function openChannel(deps: ChannelDeps): Channel {
  const connection = deps.connection.getState();
  let socket: SocketLike | null = null;
  let pingTimer: ReturnType<typeof setInterval> | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stableTimer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let stopped = false;
  let cursor: Cursor = null;
  // Frames and replays are applied strictly in arrival order.
  let inbox: Promise<void> = Promise.resolve();

  const send = (command: ClientCommand) => {
    if (socket?.readyState === SOCKET_OPEN) socket.send(JSON.stringify(command));
  };

  // Routes one envelope unless it is behind the cursor; returns the seq to
  // replay after when the envelope is ahead of it.
  const apply = (envelope: Envelope): number | null => {
    if (!isEntityChanged(envelope)) {
      deps.route(envelope);
      return null;
    }
    const placement = place(cursor, envelope.payload.seq);
    if (placement.kind === "seen") return null;
    if (placement.kind === "gap") return placement.after;
    deps.route(envelope);
    if (placement.kind === "next") cursor = placement.cursor;
    return null;
  };

  // Pages through the stream after `after`, applying each record through
  // the router; false when the fetch failed and the cursor stayed put.
  const replay = async (after: number): Promise<boolean> => {
    let from = after;
    for (;;) {
      let page: EventView[];
      try {
        page = await deps.fetchEventsAfter(from, deps.pageSize);
      } catch {
        return false;
      }
      for (const event of page) apply(eventEnvelope(event));
      if (isLastPage(page.length, deps.pageSize)) return true;
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
    deps.route(envelope);
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
      await deps.refreshAll();
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

  const clearStableTimer = () => {
    if (stableTimer) clearTimeout(stableTimer);
    stableTimer = null;
  };

  // A socket counts as connected once the server has spoken (the hello) or
  // has kept it open for a while; only then does the backoff start over. A
  // server that accepts and closes at once never gets there, so each try
  // waits longer than the last.
  const settle = () => {
    clearStableTimer();
    if (attempt === 0 && connection.status === "open") return;
    attempt = 0;
    connection.reset();
    stopPolling();
  };

  const scheduleReconnect = () => {
    if (stopped) return;
    attempt += 1;
    connection.recordFailure();
    if (deps.connection.getState().failedCycles > 1) {
      connection.setStatus("degraded");
      startPolling();
    }
    reconnectTimer = setTimeout(() => void connect(), backoffDelay(attempt));
  };

  const connect = async () => {
    if (stopped) return;
    connection.setStatus(attempt === 0 ? "connecting" : deps.connection.getState().status);
    let ticket: string;
    try {
      ticket = await deps.requestTicket();
    } catch {
      scheduleReconnect();
      return;
    }
    if (stopped) return;
    const opened = deps.openSocket(ticket);
    socket = opened;
    opened.onopen = () => {
      for (const topic of TOPICS) send({ op: "subscribe", topic });
      enqueue(catchUp);
      pingTimer = setInterval(() => send({ op: "ping" }), PING_INTERVAL_MS);
      stableTimer = setTimeout(settle, STABLE_OPEN_MS);
    };
    opened.onmessage = (message) => {
      const envelope = parseEnvelope(String(message.data));
      if (!envelope) return;
      if (envelope.type === "hello") {
        // The hello names the stream position, so a reconnect before the
        // first push replays from it instead of refreshing wholesale.
        if (cursor === null) cursor = envelope.seq;
        settle();
      }
      enqueue(() => deliver(envelope));
    };
    opened.onclose = () => {
      if (pingTimer) clearInterval(pingTimer);
      pingTimer = null;
      clearStableTimer();
      if (socket === opened) socket = null;
      if (!stopped) scheduleReconnect();
    };
    opened.onerror = () => opened.close();
  };

  void connect();

  return {
    stop: () => {
      stopped = true;
      if (pingTimer) clearInterval(pingTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      clearStableTimer();
      stopPolling();
      socket?.close();
      connection.setStatus("closed");
    },
    cursor: () => cursor,
  };
}
