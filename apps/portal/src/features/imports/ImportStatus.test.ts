// @vitest-environment jsdom
// The import cards as the page draws them from the org's recent imports:
// every one that runs or waits shows, stacked newest first, and each parked
// one carries its own Resume.
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

function draw(items: ImportView[], dismissed: Set<string> = new Set()) {
  const vm = {
    cards: shownImports(items, dismissed, OPENED).map(importCard),
    resume: vi.fn(() => Promise.resolve()),
    resuming: () => false,
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
  it("stacks two parked imports and a running one, newest first, each parked one with its Resume", () => {
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
    expect(cards.map(buttons)).toEqual([[], ["See plans", "Resume"], ["See plans", "Resume"]]);
    const resume = [...(cards[2]?.querySelectorAll("button") ?? [])].find((b) => b.textContent === "Resume");
    act(() => resume?.click());
    expect(vm.resume).toHaveBeenCalledWith("older");
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
