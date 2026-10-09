import type { EventView, TaskView } from "@tadas/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@tadas/client";
import { useConnectionStore } from "../store/connection";
import { openChannel, SOCKET_OPEN, type Channel, type SocketLike } from "./channel";
import {
  announceReminders,
  announceReminder,
  MISSED_REMINDERS_NAMED,
  missedRemindersMessage,
  reminderMessage,
  reminderNotices,
  UNNAMED_REMINDER,
  type ReminderEffects,
} from "./reminder";
import { REMINDED_KIND } from "./router";
import { eventEnvelope } from "./stream";

const task = (title: string): TaskView => ({
  id: "t1",
  title,
  notes: "",
  status: "open",
  assignee_id: null,
  rank: "0",
  created_at: "2026-09-22T10:00:00Z",
  updated_at: "2026-09-22T10:00:00Z",
  created_by: "ann",
  deleted_at: null,
  due_on: "2026-09-22",
  reminded_at: "2026-09-22T12:00:01Z",
  version: 3,
});

describe("announceReminder", () => {
  it("reads the task the push names and says its title", async () => {
    const readTask = vi.fn<ReminderEffects["readTask"]>(async () => task("Call the bank"));
    const notify = vi.fn<ReminderEffects["notify"]>();
    await expect(announceReminder("t1", { readTask, notify })).resolves.toBe("Reminder: Call the bank");
    expect(readTask).toHaveBeenCalledWith("t1");
    expect(notify).toHaveBeenCalledWith("Reminder: Call the bank");
  });

  it("still announces a task it cannot read, without the title", async () => {
    const notify = vi.fn<ReminderEffects["notify"]>();
    const readTask = async () => {
      throw new ApiError(404, "not_found", "no such task", "req_1");
    };
    await announceReminder("t1", { readTask, notify });
    expect(notify).toHaveBeenCalledWith(UNNAMED_REMINDER);
  });

  it("words a blank title as an unnamed task", () => {
    expect(reminderMessage("  Ship it ")).toBe("Reminder: Ship it");
    expect(reminderMessage("   ")).toBe(UNNAMED_REMINDER);
    expect(reminderMessage(null)).toBe(UNNAMED_REMINDER);
  });
});

describe("announceReminders", () => {
  const titles: Record<string, string> = { t1: "Call the bank", t2: "Water the plants", t3: "Pay rent", t4: "Book flights" };
  const effects = () => ({
    readTask: vi.fn<ReminderEffects["readTask"]>(async (id) => ({ ...task(titles[id]!), id })),
    notify: vi.fn<ReminderEffects["notify"]>(),
  });

  it("names each missed reminder, in stream order, up to three", async () => {
    const e = effects();
    await expect(announceReminders(["t2", "t1", "t3"], e)).resolves.toEqual([
      "Reminder: Water the plants",
      "Reminder: Call the bank",
      "Reminder: Pay rent",
    ]);
    expect(e.notify.mock.calls.map(([message]) => message)).toEqual([
      "Reminder: Water the plants",
      "Reminder: Call the bank",
      "Reminder: Pay rent",
    ]);
  });

  it("counts them in one notice past three, and reads no task", async () => {
    const e = effects();
    await announceReminders(["t1", "t2", "t3", "t4"], e);
    expect(MISSED_REMINDERS_NAMED).toBe(3);
    expect(e.notify).toHaveBeenCalledTimes(1);
    expect(e.notify).toHaveBeenCalledWith("You missed 4 reminders while you were away.");
    expect(e.readTask).not.toHaveBeenCalled();
  });

  it("counts a task reminded twice once", async () => {
    const e = effects();
    await announceReminders(["t1", "t2", "t1", "t2"], e);
    expect(e.notify.mock.calls.map(([message]) => message)).toEqual([
      "Reminder: Call the bank",
      "Reminder: Water the plants",
    ]);
  });

  it("shows nothing for none", async () => {
    const e = effects();
    await expect(announceReminders([], e)).resolves.toEqual([]);
    expect(e.notify).not.toHaveBeenCalled();
    expect(missedRemindersMessage(12)).toBe("You missed 12 reminders while you were away.");
  });
});

describe("a reminder on the channel", () => {
  class FakeSocket implements SocketLike {
    readyState = 0;
    onopen: SocketLike["onopen"] = null;
    onmessage: SocketLike["onmessage"] = null;
    onclose: SocketLike["onclose"] = null;
    onerror: SocketLike["onerror"] = null;
    accept() {
      this.readyState = SOCKET_OPEN;
      this.onopen?.({} as Event);
    }
    receive(frame: object) {
      this.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent);
    }
    drop() {
      this.readyState = 3;
      this.onclose?.({ code: 1006 } as CloseEvent);
    }
    send() {}
    close() {
      if (this.readyState !== 3) this.drop();
    }
  }

  const titles: Record<string, string> = { t1: "Call the bank", t2: "Water the plants" };
  const reminded = (seq: number, taskId: string): EventView => ({
    seq,
    kind: REMINDED_KIND,
    target_id: taskId,
    produced_at: "2026-09-22T12:00:01Z",
    actor_id: "system",
  });
  const hello = (seq: number) => ({ type: "hello", sent_at: null, org_id: "o1", user_id: "u1", seq, ping_interval_seconds: 25 });
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

  it("announces a live one once, and one missed while away once after the reconnect", async () => {
    const stream: EventView[] = [];
    const sockets: FakeSocket[] = [];
    const readTask = vi.fn<ReminderEffects["readTask"]>(async (id) => ({ ...task(titles[id]!), id }));
    const notify = vi.fn<ReminderEffects["notify"]>();
    const shown = () => notify.mock.calls.map(([message]) => message);
    channel = openChannel({
      requestTicket: async () => "tkt",
      openSocket: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      fetchEventsAfter: async (after) => stream.filter((e) => e.seq > after),
      route: () => {},
      refreshAll: async () => undefined,
      connection: useConnectionStore,
      pageSize: 200,
      ...reminderNotices({ readTask, notify }),
    });
    await flush();
    sockets[0]!.accept();
    await flush();
    sockets[0]!.receive(hello(5));
    await flush();

    stream.push(reminded(6, "t1"));
    sockets[0]!.receive(eventEnvelope(reminded(6, "t1")));
    await flush();
    expect(shown()).toEqual(["Reminder: Call the bank"]);

    // Away: the socket drops, and the next reminder fires before it is back.
    sockets[0]!.drop();
    stream.push(reminded(7, "t2"));
    await vi.advanceTimersByTimeAsync(1_000);
    sockets[1]!.accept();
    await flush();
    expect(shown()).toEqual(["Reminder: Call the bank", "Reminder: Water the plants"]);

    // A later reconnect reads neither again: the cursor has passed both.
    sockets[1]!.drop();
    await vi.advanceTimersByTimeAsync(60_000);
    sockets[2]!.accept();
    await flush();
    sockets[2]!.receive(hello(7));
    await flush();
    expect(shown()).toEqual(["Reminder: Call the bank", "Reminder: Water the plants"]);
    expect(readTask.mock.calls.map(([id]) => id)).toEqual(["t1", "t2"]);
  });
});
