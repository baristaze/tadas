// The socket loop over a fake socket and fake timers: what it sends, when it
// reconnects, and how it moves the stream cursor.
import type { EventView } from "../api";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useConnectionStore } from "../store/connection";
import { CLOSE_UNAUTHENTICATED, openChannel, SOCKET_OPEN, type Channel, type SocketLike } from "./channel";
import type { Envelope } from "./envelopes";
import { STABLE_OPEN_MS } from "./timeouts";

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: string[] = [];
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;

  /** The server accepted. */
  accept() {
    this.readyState = SOCKET_OPEN;
    this.onopen?.({} as Event);
  }
  /** The server sent a frame. */
  receive(frame: object) {
    this.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent);
  }
  /** The server closed. */
  drop(code = 1006) {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    if (this.readyState === 3) return;
    this.drop();
  }
}

function event(seq: number): EventView {
  return { seq, kind: "tasks.task.updated", target_id: `t${seq}`, produced_at: "2026-09-16T12:00:00Z", actor_id: "u1" };
}

function push(seq: number): Envelope {
  return { type: "event", topic: "entity_changed", sent_at: null, payload: { kind: "tasks.task.updated", target_id: `t${seq}`, seq, actor_id: "u1" } };
}

const seqOf = (e: Envelope) => (e as { payload: { seq: number } }).payload.seq;

const hello = (seq: number) => ({ type: "hello", sent_at: null, org_id: "o1", user_id: "u1", seq, ping_interval_seconds: 25 });

/** The stream in storage, as pages after a seq. */
type Pages = (after: number) => EventView[];

function harness(pages: Pages = () => [], pageSize = 200) {
  const sockets: FakeSocket[] = [];
  const routed: Envelope[] = [];
  const fetches: number[] = [];
  const requestTicket = vi.fn(() => Promise.resolve("tkt"));
  const onUnauthenticated = vi.fn();
  const channel = openChannel({
    onUnauthenticated,
    requestTicket,
    openSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    fetchEventsAfter: (after) => {
      fetches.push(after);
      return Promise.resolve(pages(after));
    },
    route: (envelope) => {
      routed.push(envelope);
    },
    refreshAll: () => Promise.resolve(),
    connection: useConnectionStore,
    pageSize,
  });
  return { channel, sockets, routed, fetches, requestTicket, onUnauthenticated };
}

// Lets the ticket request and the inbox settle without moving the clock.
const flush = () => vi.advanceTimersByTimeAsync(0);

let channel: Channel | null = null;

beforeEach(() => {
  vi.useFakeTimers();
  useConnectionStore.setState({ status: "closed", failedCycles: 0 });
});

afterEach(() => {
  channel?.stop();
  channel = null;
  vi.useRealTimers();
});

describe("reconnect backoff", () => {
  it("signs out on a 4401 close and never reconnects", async () => {
    const h = harness();
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    h.sockets[0]!.drop(CLOSE_UNAUTHENTICATED);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.onUnauthenticated).toHaveBeenCalledTimes(1);
    expect(h.requestTicket).toHaveBeenCalledTimes(1);
  });

  it("signs out on a 4401 close of an open channel too, as at the session's expiry", async () => {
    // The server closes a socket that said hello when the session behind it
    // expires or is revoked; the portal signs out rather than reconnecting.
    const h = harness();
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    h.sockets[0]!.receive(hello(3));
    await flush();
    h.sockets[0]!.drop(CLOSE_UNAUTHENTICATED);
    expect(useConnectionStore.getState().status).toBe("closed");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.onUnauthenticated).toHaveBeenCalledTimes(1);
    expect(h.requestTicket).toHaveBeenCalledTimes(1);
    expect(h.sockets).toHaveLength(1);
  });

  it("keeps backing off while the server accepts and closes at once", async () => {
    const h = harness();
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    h.sockets[0]!.drop();
    expect(h.requestTicket).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1_000);
    expect(h.requestTicket).toHaveBeenCalledTimes(2);
    h.sockets[1]!.accept();
    h.sockets[1]!.drop();

    // The second try waits twice as long: an accept without a hello is not a connection.
    await vi.advanceTimersByTimeAsync(1_000);
    expect(h.requestTicket).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(h.requestTicket).toHaveBeenCalledTimes(3);
    expect(useConnectionStore.getState().status).not.toBe("open");
  });

  it("starts the backoff over once the hello frame has arrived", async () => {
    const h = harness();
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    h.sockets[0]!.drop();
    await vi.advanceTimersByTimeAsync(1_000);
    h.sockets[1]!.accept();
    expect(useConnectionStore.getState().status).toBe("connecting");
    h.sockets[1]!.receive(hello(5));
    expect(useConnectionStore.getState().status).toBe("open");
    h.sockets[1]!.drop();

    // Back to the first delay.
    await vi.advanceTimersByTimeAsync(1_000);
    expect(h.requestTicket).toHaveBeenCalledTimes(3);
  });

  it("says connecting the moment an open socket drops, through the backoff and the ticket request", async () => {
    // The indicator never says live without a socket: a drop is a status
    // change on its own, not something the next successful connect fixes.
    const h = harness();
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    h.sockets[0]!.receive(hello(5));
    expect(useConnectionStore.getState().status).toBe("open");
    h.requestTicket.mockImplementation(() => new Promise(() => undefined));
    h.sockets[0]!.drop();
    expect(useConnectionStore.getState().status).toBe("connecting");
    await vi.advanceTimersByTimeAsync(1_000);
    expect(h.requestTicket).toHaveBeenCalledTimes(2);
    expect(useConnectionStore.getState().status).toBe("connecting");
  });

  it("says degraded from the second failed cycle on, through the ticket request too", async () => {
    const h = harness();
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    h.sockets[0]!.drop();
    await vi.advanceTimersByTimeAsync(1_000);
    h.sockets[1]!.accept();
    h.sockets[1]!.drop();
    expect(useConnectionStore.getState().status).toBe("degraded");
    await vi.advanceTimersByTimeAsync(2_000);
    expect(h.requestTicket).toHaveBeenCalledTimes(3);
    expect(useConnectionStore.getState().status).toBe("degraded");
  });

  it("counts a socket that stays open long enough as connected even without a hello", async () => {
    const h = harness();
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    h.sockets[0]!.drop();
    await vi.advanceTimersByTimeAsync(1_000);
    h.sockets[1]!.accept();
    await vi.advanceTimersByTimeAsync(STABLE_OPEN_MS);
    expect(useConnectionStore.getState().status).toBe("open");
    h.sockets[1]!.drop();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(h.requestTicket).toHaveBeenCalledTimes(3);
  });

  it("subscribes on open and stops for good when told to", async () => {
    const h = harness();
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    expect(h.sockets[0]!.sent).toEqual([JSON.stringify({ op: "subscribe", topic: "entity_changed" })]);
    channel.stop();
    channel = null;
    expect(h.sockets[0]!.readyState).toBe(3);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.requestTicket).toHaveBeenCalledTimes(1);
    expect(useConnectionStore.getState().status).toBe("closed");
  });
});

describe("stream cursor", () => {
  it("takes the cursor from the hello and advances on contiguous pushes", async () => {
    const h = harness();
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    await flush();
    h.sockets[0]!.receive(hello(5));
    h.sockets[0]!.receive(push(6));
    h.sockets[0]!.receive(push(7));
    await flush();
    expect(channel.cursor()).toBe(7);
    expect(h.routed.filter((e) => e.type === "event")).toHaveLength(2);
    expect(h.fetches).toEqual([]);
  });

  it("closes a gap by replaying the pages between the cursor and the push", async () => {
    const stream = [event(6), event(7), event(8)];
    const h = harness((after) => stream.filter((e) => e.seq > after).slice(0, 2), 2);
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    await flush();
    h.sockets[0]!.receive(hello(5));
    await flush();
    h.sockets[0]!.receive(push(8));
    await flush();
    expect(h.fetches).toEqual([5, 7]);
    expect(channel.cursor()).toBe(8);
    expect(h.routed.filter((e) => e.type === "event").map(seqOf)).toEqual([6, 7, 8]);
  });

  it("stops paging when a page moves the cursor nowhere", async () => {
    // Seq 6 is not in storage yet; every page after 5 starts at 7 and is full.
    const stream = [event(7), event(8), event(9)];
    let calls = 0;
    const h = harness((after) => {
      calls += 1;
      if (calls > 3) throw new Error("hammered");
      return stream.filter((e) => e.seq > after).slice(0, 2);
    }, 2);
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    await flush();
    h.sockets[0]!.receive(hello(5));
    await flush();
    h.sockets[0]!.receive(push(9));
    await flush();
    expect(h.fetches).toEqual([5]);
    expect(channel.cursor()).toBe(5);
    // The push is still worth routing: the entity did change.
    expect(h.routed.filter((e) => e.type === "event").map(seqOf)).toEqual([9]);
  });

  it("never moves the cursor past seqs that were not replayed", async () => {
    // Storage answers with a short page that skips 6: the replay ends, the gap stays.
    const h = harness((after) => [event(7), event(8)].filter((e) => e.seq > after));
    channel = h.channel;
    await flush();
    h.sockets[0]!.accept();
    await flush();
    h.sockets[0]!.receive(hello(5));
    await flush();
    h.sockets[0]!.receive(push(8));
    await flush();
    expect(h.routed.filter((e) => e.type === "event").map(seqOf)).toEqual([8]);
    expect(channel.cursor()).toBe(5);

    // Once 6 exists, the next push replays through it and the cursor catches up.
    const h2 = h;
    h2.sockets[0]!.receive(push(6));
    await flush();
    expect(channel.cursor()).toBe(6);
  });
});
