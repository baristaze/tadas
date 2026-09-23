// Pure: a task's due time, between the wire and the screen. The wire carries
// ISO 8601 with an offset; the screen shows and takes the browser's local
// time, through a `datetime-local` input, whose value has no offset.
import type { TaskView } from "../../api";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const LONG_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const LONG_MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DAY_MS = 86_400_000;

const two = (n: number) => String(n).padStart(2, "0");

/** A due time is upcoming, past with its reminder not out yet, or reminded. */
export type DueState = "upcoming" | "past" | "reminded";

export interface DueBadge {
  state: DueState;
  /** The short text on the row, e.g. "due Tue 14:30". */
  text: string;
  /** The whole date, for the tooltip. */
  title: string;
}

function parse(iso: string): Date | null {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

function clock(date: Date): string {
  return `${two(date.getHours())}:${two(date.getMinutes())}`;
}

function dayNumber(date: Date): number {
  return Math.round(new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime() / DAY_MS);
}

/** Short and local: the weekday within six days either side of today, the
 * month and day further out, and the year too when it is not this one. */
export function formatDue(date: Date, now: Date): string {
  if (Math.abs(dayNumber(date) - dayNumber(now)) <= 6) return `${DAYS[date.getDay()]} ${clock(date)}`;
  const day = `${MONTHS[date.getMonth()]} ${date.getDate()}`;
  const year = date.getFullYear() === now.getFullYear() ? "" : ` ${date.getFullYear()}`;
  return `${day}${year} ${clock(date)}`;
}

export function formatDueLong(date: Date): string {
  return `${LONG_DAYS[date.getDay()]} ${date.getDate()} ${LONG_MONTHS[date.getMonth()]} ${date.getFullYear()}, ${clock(date)}`;
}

export function dueState(task: Pick<TaskView, "remind_at" | "reminded_at">, now: Date): DueState | null {
  const due = task.remind_at ? parse(task.remind_at) : null;
  if (!due) return null;
  if (task.reminded_at) return "reminded";
  return due.getTime() <= now.getTime() ? "past" : "upcoming";
}

export function dueBadge(task: Pick<TaskView, "remind_at" | "reminded_at">, now: Date): DueBadge | null {
  const state = dueState(task, now);
  const due = task.remind_at ? parse(task.remind_at) : null;
  if (!state || !due) return null;
  const short = formatDue(due, now);
  const long = formatDueLong(due);
  if (state === "reminded") return { state, text: `reminded ${short}`, title: `Due ${long}. The reminder went out.` };
  if (state === "past") return { state, text: `due ${short}`, title: `Due ${long}. The time has passed.` };
  return { state, text: `due ${short}`, title: `Due ${long}` };
}

/** The value a `datetime-local` input shows for a due time: local, to the minute. */
export function toInputValue(iso: string | null): string {
  const date = iso ? parse(iso) : null;
  if (!date) return "";
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}T${clock(date)}`;
}

/** The wire value for what a `datetime-local` input holds: the local time
 * with the browser's offset for that moment. Null for an empty or partial value. */
export function fromInputValue(value: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const [, y, mo, d, h, mi] = match.map(Number) as [number, number, number, number, number, number];
  const date = new Date(y, mo - 1, d, h, mi);
  if (Number.isNaN(date.getTime()) || date.getMonth() !== mo - 1 || date.getDate() !== d) return null;
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  return (
    `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}` +
    `T${clock(date)}:00${sign}${two(Math.floor(abs / 60))}:${two(abs % 60)}`
  );
}

/** What an edit sends as `remind_at`: undefined when the input did not change,
 * so the field is left out and the due time kept; null when it was emptied,
 * which clears it; the new time otherwise, which reschedules. */
export function remindAtChange(initial: string, current: string): string | null | undefined {
  if (current.trim() === initial.trim()) return undefined;
  return fromInputValue(current);
}
