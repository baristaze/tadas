import type { TaskView } from "../api";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { announceReminder, reminderMessage, UNNAMED_REMINDER, type ReminderEffects } from "./reminder";

const task = (title: string): TaskView => ({
  id: "t1",
  title,
  notes: "",
  status: "open",
  assignee_id: null,
  position: 0,
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
