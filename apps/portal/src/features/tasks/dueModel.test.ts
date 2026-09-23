import { describe, expect, it } from "vitest";
import { dueBadge, dueState, formatDue, fromInputValue, remindAtChange, toInputValue } from "./dueModel";

// Local times throughout: the model shows and takes the browser's zone, so the
// test builds its moments in whatever zone it runs in.
const now = new Date(2026, 8, 22, 12, 0); // Tuesday 22 September 2026, 12:00
const at = (day: number, hour: number, minute = 0, month = 8, year = 2026) =>
  new Date(year, month, day, hour, minute).toISOString();

describe("due model", () => {
  it("says the weekday near today and the date further out", () => {
    expect(formatDue(new Date(2026, 8, 22, 14, 30), now)).toBe("Tue 14:30");
    expect(formatDue(new Date(2026, 8, 25, 9, 5), now)).toBe("Fri 09:05");
    expect(formatDue(new Date(2026, 8, 16, 8, 0), now)).toBe("Wed 08:00");
    expect(formatDue(new Date(2026, 8, 30, 14, 30), now)).toBe("Sep 30 14:30");
    expect(formatDue(new Date(2027, 0, 4, 7, 0), now)).toBe("Jan 4 2027 07:00");
  });

  it("knows an upcoming, a past, and a reminded due time", () => {
    expect(dueState({ remind_at: null, reminded_at: null }, now)).toBeNull();
    expect(dueState({ remind_at: at(22, 14, 30), reminded_at: null }, now)).toBe("upcoming");
    expect(dueState({ remind_at: at(22, 11), reminded_at: null }, now)).toBe("past");
    expect(dueState({ remind_at: at(22, 11), reminded_at: at(22, 11) }, now)).toBe("reminded");
    expect(dueState({ remind_at: "not a time", reminded_at: null }, now)).toBeNull();
  });

  it("builds the badge a row shows", () => {
    expect(dueBadge({ remind_at: null, reminded_at: null }, now)).toBeNull();
    expect(dueBadge({ remind_at: at(22, 14, 30), reminded_at: null }, now)).toEqual({
      state: "upcoming",
      text: "due Tue 14:30",
      title: "Due Tuesday 22 September 2026, 14:30",
    });
    expect(dueBadge({ remind_at: at(22, 11), reminded_at: null }, now)).toMatchObject({
      state: "past",
      text: "due Tue 11:00",
    });
    expect(dueBadge({ remind_at: at(21, 9), reminded_at: at(21, 9) }, now)).toEqual({
      state: "reminded",
      text: "reminded Mon 09:00",
      title: "Due Monday 21 September 2026, 09:00. The reminder went out.",
    });
  });

  it("round-trips a local time through the input and the wire", () => {
    expect(toInputValue(null)).toBe("");
    expect(toInputValue(at(22, 14, 30))).toBe("2026-09-22T14:30");
    const wire = fromInputValue("2026-09-22T14:30");
    expect(wire).toMatch(/^2026-09-22T14:30:00[+-]\d{2}:\d{2}$/);
    expect(new Date(wire!).getTime()).toBe(new Date(2026, 8, 22, 14, 30).getTime());
    expect(toInputValue(wire)).toBe("2026-09-22T14:30");
  });

  it("refuses an empty or partial input", () => {
    expect(fromInputValue("")).toBeNull();
    expect(fromInputValue("2026-09-22")).toBeNull();
    expect(fromInputValue("2026-02-30T10:00")).toBeNull();
  });

  it("sends a due time only when the edit changed it, and null to clear it", () => {
    expect(remindAtChange("", "")).toBeUndefined();
    expect(remindAtChange("2026-09-22T14:30", "2026-09-22T14:30")).toBeUndefined();
    expect(remindAtChange("2026-09-22T14:30", "")).toBeNull();
    expect(remindAtChange("", "2026-09-23T09:00")).toBe(fromInputValue("2026-09-23T09:00"));
  });
});
