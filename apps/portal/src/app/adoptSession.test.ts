// Runs without a browser: an in-memory Storage stands in for the tab's
// session storage, as forgetSession's own test does.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

beforeEach(() => {
  vi.stubGlobal("sessionStorage", new MemoryStorage());
  vi.stubGlobal("localStorage", new MemoryStorage());
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const org = (slug: string) => ({ id: slug, name: slug, slug, kind: "team" as const, created_at: "2026-09-01T00:00:00Z" });

describe("adoptSession", () => {
  it("drops every answer of the old tenant before the new session is set", async () => {
    const { adoptSession } = await import("./adoptSession");
    const { queryClient } = await import("./queryClient");
    const { useSessionStore } = await import("../store/session");
    useSessionStore.getState().setSession("ses_old", "acme");
    queryClient.setQueryData(["me"], { org: { slug: "acme" } });
    queryClient.setQueryData(["task", "open", "team"], { items: [{ title: "Acme's task" }] });

    adoptSession({ token: "ses_new", org: org("beta") });

    expect(useSessionStore.getState().token).toBe("ses_new");
    expect(useSessionStore.getState().orgSlug).toBe("beta");
    expect(queryClient.getQueryCache().getAll()).toEqual([]);
    expect(JSON.parse(sessionStorage.getItem("tadas.portal.session") ?? "{}").state.token).toBe("ses_new");
    expect(localStorage.length).toBe(0);
  });
});
