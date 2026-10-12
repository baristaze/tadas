// The store runs here without a browser: an in-memory Storage twin stands in
// for the origin's local storage.
import type { ImportView } from "@tadas/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { shownImports } from "../features/imports/importModel";

const KEY = "tadas.portal.preferences";
const LEGACY = "tadas.portal.taskScope";

class MemoryStorage implements Storage {
  private items = new Map<string, string>();
  get length() {
    return this.items.size;
  }
  clear() {
    this.items.clear();
  }
  getItem(key: string) {
    return this.items.get(key) ?? null;
  }
  key(index: number) {
    return [...this.items.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.items.delete(key);
  }
  setItem(key: string, value: string) {
    this.items.set(key, value);
  }
}

let local: MemoryStorage;

beforeEach(() => {
  local = new MemoryStorage();
  vi.stubGlobal("localStorage", local);
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("preferences store", () => {
  it("starts on my tasks and keeps the chosen scope in local storage", async () => {
    const { usePreferencesStore } = await import("./preferences");
    expect(usePreferencesStore.getState().taskScope).toBe("mine");
    usePreferencesStore.getState().setTaskScope("team");
    expect(JSON.parse(local.getItem(KEY) as string).state).toEqual({ taskScope: "team", theme: "system", folded: {}, dismissedImports: {} });
  });

  it("follows the system until a theme is picked, and keeps the pick", async () => {
    const { usePreferencesStore } = await import("./preferences");
    expect(usePreferencesStore.getState().theme).toBe("system");
    usePreferencesStore.getState().setTheme("dark");
    expect(JSON.parse(local.getItem(KEY) as string).state).toEqual({ taskScope: "mine", theme: "dark", folded: {}, dismissedImports: {} });
  });

  it("reads a stored theme back, and an unknown one as the system's", async () => {
    local.setItem(KEY, JSON.stringify({ state: { taskScope: "team", theme: "light" }, version: 0 }));
    let { usePreferencesStore } = await import("./preferences");
    expect(usePreferencesStore.getState().theme).toBe("light");
    vi.resetModules();
    local.setItem(KEY, JSON.stringify({ state: { taskScope: "team", theme: "sepia" }, version: 0 }));
    ({ usePreferencesStore } = await import("./preferences"));
    expect(usePreferencesStore.getState().theme).toBe("system");
    expect(usePreferencesStore.getState().taskScope).toBe("team");
  });

  it("drops a stored field it does not know", async () => {
    local.setItem(KEY, JSON.stringify({ state: { theme: "dark", other: "x" }, version: 0 }));
    const { usePreferencesStore } = await import("./preferences");
    expect(usePreferencesStore.getState()).not.toHaveProperty("other");
    usePreferencesStore.getState().setTheme("light");
    expect(JSON.parse(local.getItem(KEY) as string).state).toEqual({ taskScope: "mine", theme: "light", folded: {}, dismissedImports: {} });
  });

  it("reads the scope back on the next visit, and a scope it does not know as the default", async () => {
    local.setItem(KEY, JSON.stringify({ state: { taskScope: "team" }, version: 0 }));
    let { usePreferencesStore } = await import("./preferences");
    expect(usePreferencesStore.getState().taskScope).toBe("team");
    vi.resetModules();
    local.setItem(KEY, JSON.stringify({ state: { taskScope: "everything" }, version: 0 }));
    ({ usePreferencesStore } = await import("./preferences"));
    expect(usePreferencesStore.getState().taskScope).toBe("mine");
  });

  it("adopts the scope an earlier build kept as a bare word, once", async () => {
    local.setItem(LEGACY, "team");
    const { usePreferencesStore } = await import("./preferences");
    expect(usePreferencesStore.getState().taskScope).toBe("team");
    expect(local.getItem(LEGACY)).toBeNull();
  });

  it("ignores a bare word that is not a scope, and a storage that throws", async () => {
    const { adoptLegacyScope, legacyScope } = await import("./preferences");
    expect(legacyScope("everything")).toBeNull();
    expect(legacyScope(null)).toBeNull();
    const throwing = {
      getItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => undefined,
    };
    expect(adoptLegacyScope(throwing)).toBeNull();
    expect(adoptLegacyScope(undefined)).toBeNull();
  });

  it("folds Done and not Open at first, and keeps each fold per org", async () => {
    const { isFolded, usePreferencesStore } = await import("./preferences");
    const folded = () => usePreferencesStore.getState().folded;
    expect(isFolded(folded(), "org-a", "open")).toBe(false);
    expect(isFolded(folded(), "org-a", "done")).toBe(true);
    expect(isFolded(folded(), null, "done")).toBe(true);
    usePreferencesStore.getState().setFolded("org-a", "done", false);
    usePreferencesStore.getState().setFolded("org-a", "open", true);
    expect(isFolded(folded(), "org-a", "done")).toBe(false);
    expect(isFolded(folded(), "org-a", "open")).toBe(true);
    expect(isFolded(folded(), "org-b", "done")).toBe(true);
    expect(JSON.parse(local.getItem(KEY) as string).state.folded).toEqual({
      "org-a": { done: false, open: true },
    });
  });

  it("reads the folds back on the next visit, and drops folds it cannot read", async () => {
    local.setItem(KEY, JSON.stringify({ state: { taskScope: "team", folded: { "org-a": { done: false } } }, version: 0 }));
    const first = await import("./preferences");
    expect(first.isFolded(first.usePreferencesStore.getState().folded, "org-a", "done")).toBe(false);
    vi.resetModules();
    local.setItem(KEY, JSON.stringify({ state: { folded: "nonsense" }, version: 0 }));
    const second = await import("./preferences");
    expect(second.usePreferencesStore.getState().folded).toEqual({});
  });

  it("keeps a dismissed import gone across a reload, and prunes one no longer recent", async () => {
    const ended = (id: string) =>
      ({ id, status: "succeeded", created_at: "2026-09-25T10:00:00Z", finished_at: "2026-09-25T10:04:00Z" }) as ImportView;
    const openedAt = Date.parse("2026-09-25T10:05:00Z");
    const recent = [ended("i2"), ended("i1")];
    const first = await import("./preferences");
    first.usePreferencesStore.getState().dismissImport("org-a", "i1");
    vi.resetModules();
    const { usePreferencesStore } = await import("./preferences");
    const kept = () => usePreferencesStore.getState().dismissedImports;
    expect(kept()).toEqual({ "org-a": ["i1"] });
    const shown = shownImports(recent, new Set(kept()["org-a"]), openedAt);
    expect(shown.map((v) => v.id)).toEqual(["i2"]);
    usePreferencesStore.getState().dismissImport("org-a", "i2");
    usePreferencesStore.getState().pruneDismissedImports("org-a", ["i2", "i3"]);
    expect(JSON.parse(local.getItem(KEY) as string).state.dismissedImports).toEqual({ "org-a": ["i2"] });
    usePreferencesStore.getState().pruneDismissedImports("org-a", ["i3"]);
    expect(JSON.parse(local.getItem(KEY) as string).state.dismissedImports).toEqual({});
  });

  it("keeps only lists of ids from a stored dismissal it cannot read whole", async () => {
    local.setItem(
      KEY,
      JSON.stringify({ state: { dismissedImports: { "org-a": ["i1", 7, null], "org-b": "i2", "org-c": [] } }, version: 0 }),
    );
    let { usePreferencesStore } = await import("./preferences");
    expect(usePreferencesStore.getState().dismissedImports).toEqual({ "org-a": ["i1"] });
    vi.resetModules();
    local.setItem(KEY, JSON.stringify({ state: { dismissedImports: ["i1"] }, version: 0 }));
    ({ usePreferencesStore } = await import("./preferences"));
    expect(usePreferencesStore.getState().dismissedImports).toEqual({});
  });
});
