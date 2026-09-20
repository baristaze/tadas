import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NOTICE_TTL_MS, notify, useNoticesStore } from "./notices";

beforeEach(() => {
  vi.useFakeTimers();
  useNoticesStore.setState({ notices: [] });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("notices store", () => {
  it("keeps what it is told, in order, until each is dismissed", () => {
    const first = notify("The key was not created.");
    const second = notify("The key was not revoked.");
    expect(useNoticesStore.getState().notices.map((n) => n.message)).toEqual([
      "The key was not created.",
      "The key was not revoked.",
    ]);
    useNoticesStore.getState().dismiss(first);
    expect(useNoticesStore.getState().notices.map((n) => n.id)).toEqual([second]);
  });

  it("lets a notice go on its own after a while", () => {
    notify("gone soon");
    vi.advanceTimersByTime(NOTICE_TTL_MS - 1);
    expect(useNoticesStore.getState().notices).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(useNoticesStore.getState().notices).toHaveLength(0);
  });

  it("gives every notice its own id", () => {
    expect(notify("a")).not.toBe(notify("a"));
  });
});
