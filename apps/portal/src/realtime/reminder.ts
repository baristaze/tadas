// A reminder as one flow with its effects handed in, so it runs in a test
// without React. The push carries the task's id only, so the title is read
// from the server; a task that cannot be read (deleted since, or the network
// failed) is still announced, without its title.
import type { TaskView } from "../api";

export interface ReminderEffects {
  /** Reads the task the push names. */
  readTask: (id: string) => Promise<TaskView>;
  /** Shows one notice. */
  notify: (message: string) => void;
}

export const UNNAMED_REMINDER = "Reminder: a task is due.";

export function reminderMessage(title: string | null): string {
  const trimmed = title?.trim();
  return trimmed ? `Reminder: ${trimmed}` : UNNAMED_REMINDER;
}

export async function announceReminder(taskId: string, effects: ReminderEffects): Promise<string> {
  let title: string | null;
  try {
    title = (await effects.readTask(taskId)).title;
  } catch {
    title = null;
  }
  const message = reminderMessage(title);
  effects.notify(message);
  return message;
}
