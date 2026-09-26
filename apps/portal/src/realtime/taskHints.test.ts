import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TaskView } from "../api";
import { createTaskHints, HINT_BURST, HINT_WINDOW_MS, ReadAsList, type TaskHintEffects } from "./taskHints";

const task = (id: string, version = 1) => ({ id, version }) as TaskView;

class Gone extends Error {}

function effects(answer: (id: string) => Promise<TaskView> = async (id) => task(id)) {
  let clock = 7;
  const fx = {
    readTask: vi.fn<TaskHintEffects["readTask"]>(answer),
    isGone: (cause: unknown) => cause instanceof Gone,
    stamp: vi.fn(() => clock++),
    place: vi.fn<TaskHintEffects["place"]>(),
    remove: vi.fn<TaskHintEffects["remove"]>(),
    refreshLists: vi.fn<TaskHintEffects["refreshLists"]>(),
  };
  return fx;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const settle = () => vi.advanceTimersByTimeAsync(HINT_WINDOW_MS);

describe("createTaskHints", () => {
  it("reads one task per hint and places the answer with the stamp of its issue", async () => {
    const fx = effects();
    const hints = createTaskHints(fx);
    const read = hints.hint("t1");
    expect(fx.readTask).not.toHaveBeenCalled(); // gathered first
    await settle();
    expect(fx.readTask.mock.calls).toEqual([["t1"]]);
    expect(fx.place).toHaveBeenCalledWith(task("t1"), 7);
    expect(fx.refreshLists).not.toHaveBeenCalled();
    await expect(read).resolves.toEqual(task("t1"));
  });

  it("reads a task pushed twice in one window once", async () => {
    const fx = effects();
    const hints = createTaskHints(fx);
    const first = hints.hint("t1");
    const second = hints.hint("t1");
    hints.hint("t2");
    await settle();
    expect(fx.readTask.mock.calls).toEqual([["t1"], ["t2"]]);
    expect(first).toBe(second);
  });

  it("reads a task again when it is pushed in a later window", async () => {
    const fx = effects();
    const hints = createTaskHints(fx);
    hints.hint("t1");
    await settle();
    hints.hint("t1");
    await settle();
    expect(fx.readTask).toHaveBeenCalledTimes(2);
  });

  it("takes a task out when its read answers 404", async () => {
    const fx = effects(async () => {
      throw new Gone();
    });
    const hints = createTaskHints(fx);
    const read = hints.hint("t1");
    await settle();
    expect(fx.remove).toHaveBeenCalledWith("t1", 7);
    expect(fx.place).not.toHaveBeenCalled();
    expect(fx.refreshLists).not.toHaveBeenCalled();
    await expect(read).resolves.toBeNull();
  });

  it("reads the lists once when a read fails for another reason", async () => {
    const fx = effects(async (id) => {
      if (id === "t2") throw new Error("offline");
      return task(id);
    });
    const hints = createTaskHints(fx);
    hints.hint("t1");
    hints.hint("t2");
    hints.hint("t3");
    await settle();
    expect(fx.place).toHaveBeenCalledTimes(2);
    expect(fx.refreshLists).toHaveBeenCalledTimes(1);
  });

  it(`reads single tasks up to ${HINT_BURST} in a window`, async () => {
    const fx = effects();
    const hints = createTaskHints(fx);
    for (let i = 0; i < HINT_BURST; i += 1) hints.hint(`t${i}`);
    await settle();
    expect(fx.readTask).toHaveBeenCalledTimes(HINT_BURST);
    expect(fx.refreshLists).not.toHaveBeenCalled();
  });

  it(`reads the lists once, and no task, past ${HINT_BURST} tasks in a window`, async () => {
    // An import step, or a move that renumbers the open list.
    const fx = effects();
    const hints = createTaskHints(fx);
    const reads = Array.from({ length: 50 }, (_, i) => hints.hint(`t${i}`));
    await settle();
    expect(fx.readTask).not.toHaveBeenCalled();
    expect(fx.refreshLists).toHaveBeenCalledTimes(1);
    await expect(reads[0]).rejects.toBeInstanceOf(ReadAsList);
  });

  it("places one window's answers together, after the last read lands", async () => {
    const answers = new Map<string, (task: TaskView) => void>();
    const fx = effects((id) => new Promise((resolve) => answers.set(id, resolve)));
    const hints = createTaskHints(fx);
    hints.hint("t1");
    hints.hint("t2");
    await settle();
    answers.get("t1")!(task("t1"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fx.place).not.toHaveBeenCalled();
    answers.get("t2")!(task("t2"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fx.place.mock.calls.map(([t]) => t.id)).toEqual(["t1", "t2"]);
  });

  it("reads nothing once stopped", async () => {
    const fx = effects();
    const hints = createTaskHints(fx);
    const read = hints.hint("t1");
    hints.stop();
    await settle();
    expect(fx.readTask).not.toHaveBeenCalled();
    await expect(read).rejects.toThrow();
  });
});
