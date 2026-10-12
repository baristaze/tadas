// @vitest-environment jsdom
// The import cards over the view model and a fake transport: a parked
// import's Cancel asks first, its yes posts the cancel, and the card the
// refreshed list draws reads cancelled, with nothing left to resume.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ImportView } from "@tadas/client";
import { ImportStatus } from "./ImportStatus";
import { useImportVm } from "./useImportVm";

interface Held {
  path: string;
  resolve: (value: unknown) => void;
}

const net = vi.hoisted(() => {
  const reads = new Map<string, unknown>();
  const writes: Held[] = [];
  return {
    reads,
    writes,
    get: (path: string) => {
      for (const [prefix, value] of reads) if (path.startsWith(prefix)) return Promise.resolve(value);
      return Promise.reject(new Error(`no read stubbed for ${path}`));
    },
    post: (path: string) => new Promise((resolve) => writes.push({ path, resolve })),
  };
});

vi.mock("../../app/api", () => ({ api: { get: net.get, post: net.post } }));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

function view(fields: Partial<ImportView>): ImportView {
  return {
    id: "i1",
    file_id: "f1",
    status: "parked",
    total: 15,
    cursor: 10,
    created: 10,
    skipped: 0,
    row_errors: [],
    park_reason: "plan_limit",
    fail_reason: null,
    created_at: "2026-09-25T10:00:00Z",
    updated_at: "2026-09-25T10:00:00Z",
    finished_at: null,
    created_by: "u1",
    ...fields,
  };
}

function Page() {
  return createElement(ImportStatus, { vm: useImportVm(true) });
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const tick = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
const card = () => host.querySelector("[role=status]");
const headline = () => card()?.firstElementChild?.firstElementChild?.textContent;
const buttons = () => [...(card()?.querySelectorAll("button") ?? [])];
const press = (label: string) =>
  act(async () => {
    buttons()
      .find((b) => b.textContent === label)
      ?.click();
  });

beforeEach(async () => {
  net.reads.clear();
  net.writes.length = 0;
  net.reads.set("/v1/tasks/imports", { items: [view({})] });
  net.reads.set("/v1/me", { org: { id: "o1" } });
  net.reads.set("/v1/billing", { can_manage: false });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(createElement(QueryClientProvider, { client: queryClient }, createElement(Page)));
  });
  await tick();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("cancels a parked import on the second yes, and its card then reads cancelled", async () => {
  expect(buttons().map((b) => b.textContent)).toEqual(["Resume", "Cancel"]);
  await press("Cancel");
  expect(net.writes).toEqual([]);
  expect(buttons().map((b) => b.textContent)).toEqual(["Cancel import", "Keep it"]);

  await press("Cancel import");
  expect(net.writes.map((w) => w.path)).toEqual(["/v1/tasks/imports/i1/cancel"]);
  const cancelled = view({ status: "cancelled", park_reason: null, finished_at: new Date().toISOString() });
  net.reads.set("/v1/tasks/imports", { items: [cancelled] });
  await act(async () => net.writes[0]!.resolve(cancelled));
  await tick();
  expect(headline()).toBe("Import cancelled. Created 10 of 15.");
  expect(buttons().map((b) => b.textContent)).toEqual(["Dismiss"]);
});

it("keeps the import as it was when the person says Keep it", async () => {
  await press("Cancel");
  await press("Keep it");
  expect(net.writes).toEqual([]);
  expect(buttons().map((b) => b.textContent)).toEqual(["Resume", "Cancel"]);
});
