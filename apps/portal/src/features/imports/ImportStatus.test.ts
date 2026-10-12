// @vitest-environment jsdom
// The import cards as the page draws them from the org's recent imports:
// every one that runs or waits shows, stacked newest first, each parked one
// carries its own Resume, and every one that runs or waits its Cancel, which
// asks before it ends the import.
import type { ImportView } from "@tadas/client";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { importCard, shownImports } from "./importModel";
import { ImportStatus } from "./ImportStatus";
import type { ImportVm } from "./useImportVm";

function view(fields: Partial<ImportView>): ImportView {
  return {
    id: "i1",
    file_id: "f1",
    status: "running",
    total: 50,
    cursor: 20,
    created: 20,
    skipped: 0,
    row_errors: [],
    park_reason: null,
    fail_reason: null,
    created_at: "2026-09-25T10:00:00Z",
    updated_at: "2026-09-25T10:00:00Z",
    finished_at: null,
    created_by: "u1",
    ...fields,
  };
}

const OPENED = Date.parse("2026-09-25T10:05:00Z");

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function draw(items: ImportView[], dismissed: Set<string> = new Set(), asking: string | null = null) {
  const vm = {
    cards: shownImports(items, dismissed, OPENED).map(importCard),
    resume: vi.fn(() => Promise.resolve()),
    resuming: () => false,
    askingCancel: (id: string) => id === asking,
    askCancel: vi.fn(),
    keepImport: vi.fn(),
    cancel: vi.fn(() => Promise.resolve()),
    cancelling: () => false,
    dismiss: vi.fn(),
    upgrade: vi.fn(),
    canUpgrade: true,
  } as unknown as ImportVm;
  act(() => root.render(createElement(ImportStatus, { vm })));
  const cards = [...host.querySelectorAll("[role=status]")];
  const buttons = (card: Element) => [...card.querySelectorAll("button")].map((b) => b.textContent);
  return { vm, cards, buttons };
}

describe("ImportStatus", () => {
  it("stacks two parked imports and a running one, newest first, each parked one with its Resume and Cancel", () => {
    const { vm, cards, buttons } = draw([
      view({ id: "older", status: "parked", park_reason: "plan_limit", cursor: 10, created: 10, total: 15, created_at: "2026-09-25T09:00:00Z" }),
      view({ id: "running", total: null, cursor: 0, created: 0, created_at: "2026-09-25T10:00:00Z" }),
      view({ id: "newer", status: "parked", park_reason: "plan_limit", cursor: 0, created: 0, total: 25, created_at: "2026-09-25T09:30:00Z" }),
    ]);
    expect(cards.map((c) => c.firstElementChild?.firstElementChild?.textContent)).toEqual([
      "Importing tasks…",
      "Import paused at your plan's limit of active tasks. Created 0 of 25.",
      "Import paused at your plan's limit of active tasks. Created 10 of 15.",
    ]);
    expect(cards.map(buttons)).toEqual([
      ["Cancel"],
      ["See plans", "Resume", "Cancel"],
      ["See plans", "Resume", "Cancel"],
    ]);
    const resume = [...(cards[2]?.querySelectorAll("button") ?? [])].find((b) => b.textContent === "Resume");
    act(() => resume?.click());
    expect(vm.resume).toHaveBeenCalledWith("older");
  });

  it("asks before a Cancel ends the import, and Keep it leaves it as it was", () => {
    const parked = view({ id: "parked", status: "parked", park_reason: "plan_limit", cursor: 10, created: 10, total: 15 });
    const first = draw([parked]);
    const cancel = [...(first.cards[0]?.querySelectorAll("button") ?? [])].find((b) => b.textContent === "Cancel");
    act(() => cancel?.click());
    expect(first.vm.askCancel).toHaveBeenCalledWith("parked");
    expect(first.vm.cancel).not.toHaveBeenCalled();

    const { vm, cards, buttons } = draw([parked], new Set(), "parked");
    expect(cards.map(buttons)).toEqual([["Cancel import", "Keep it"]]);
    expect(cards[0]?.textContent).toContain("The tasks it made stay, and the rest of the file is not imported.");
    const [yes, no] = [...(cards[0]?.querySelectorAll("button") ?? [])];
    act(() => no?.click());
    expect(vm.keepImport).toHaveBeenCalled();
    act(() => yes?.click());
    expect(vm.cancel).toHaveBeenCalledWith("parked");
  });

  it("says a cancelled import was cancelled, and offers only Dismiss", () => {
    const cancelled = view({
      id: "cancelled",
      status: "cancelled",
      cursor: 10,
      created: 10,
      total: 15,
      finished_at: "2026-09-25T10:04:00Z",
    });
    const { cards, buttons } = draw([cancelled], new Set(), "cancelled");
    expect(cards[0]?.firstElementChild?.firstElementChild?.textContent).toBe("Import cancelled. Created 10 of 15.");
    expect(cards.map(buttons)).toEqual([["Dismiss"]]);
  });

  it("offers Dismiss on an import that ended, and draws nothing once it is dismissed", () => {
    const ended = view({ id: "ended", status: "succeeded", finished_at: "2026-09-25T10:04:00Z" });
    const { vm, cards, buttons } = draw([ended]);
    expect(cards.map(buttons)).toEqual([["Dismiss"]]);
    act(() => cards[0]?.querySelector("button")?.click());
    expect(vm.dismiss).toHaveBeenCalledWith("ended");
    expect(draw([ended], new Set(["ended"])).cards).toEqual([]);
  });
});
