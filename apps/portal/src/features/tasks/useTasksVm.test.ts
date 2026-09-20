// @vitest-environment jsdom
// The view model over a fake transport: every write is held open, so a second
// write can start while the first is still in flight. That is the case the
// screen hits when someone ticks two tasks in a row, or submits one edit twice.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, type MeView, type TaskPageView, type TaskView, type UserPageView } from "../../api";
import { STALE_MESSAGE } from "./reorder";
import { useTasksVm, type TasksVm } from "./useTasksVm";

interface Held {
  method: string;
  path: string;
  body: unknown;
  resolve: (value: unknown) => void;
  reject: (cause: unknown) => void;
}

const net = vi.hoisted(() => {
  const reads = new Map<string, unknown>();
  const writes: Held[] = [];
  const read = (path: string) => {
    for (const [prefix, value] of reads) if (path.startsWith(prefix)) return Promise.resolve(value);
    return Promise.reject(new Error(`no read stubbed for ${path}`));
  };
  const hold = (method: string) => (path: string, body?: unknown) =>
    new Promise((resolve, reject) => writes.push({ method, path, body, resolve, reject }));
  return { reads, writes, read, hold };
});

vi.mock("../../app/api", () => ({
  api: { get: net.read, post: net.hold("POST"), patch: net.hold("PATCH"), del: net.hold("DELETE") },
}));

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
let root: ReturnType<typeof createRoot>;

const me: MeView = {
  app: "portal",
  role: "owner",
  permissions: ["read", "write"],
  user: { id: "u1", email: "owner@example.test", display_name: "Owner", created_at: "2026-09-01T00:00:00Z" },
  org: { id: "o1", name: "Acme", slug: "acme", created_at: "2026-09-01T00:00:00Z", deleted_at: null },
};

const taskOf = (id: string, title: string): TaskView => ({
  id,
  title,
  notes: "",
  status: "open",
  assignee_id: null,
  position: 0,
  version: 1,
  created_by: "u1",
  deleted_at: null,
  created_at: "2026-09-20T10:00:00Z",
  updated_at: "2026-09-20T10:00:00Z",
});

const alpha = taskOf("t1", "Alpha");
const beta = taskOf("t2", "Beta");

// The view model as the screen sees it, taken after each commit rather than
// during render, so the probe stays a pure component.
const held: { vm?: TasksVm } = {};
const vm = () => held.vm!;

function Probe() {
  const current = useTasksVm();
  useEffect(() => {
    held.vm = current;
  });
  return null;
}

const tick = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

async function mount() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      createElement(QueryClientProvider, { client: queryClient }, createElement(Probe)),
    );
  });
  // The two lists and the member walk settle over a few turns of the loop.
  for (let turn = 0; turn < 50 && vm().loading; turn += 1) await tick();
  expect(vm().loading).toBe(false);
}

beforeEach(() => {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  held.vm = undefined;
  net.reads.clear();
  net.writes.length = 0;
  net.reads.set("/v1/me", me);
  net.reads.set("/v1/users", { items: [me.user], next_cursor: null } satisfies UserPageView);
  net.reads.set("/v1/tasks?status=open", { items: [alpha, beta], next_cursor: null } satisfies TaskPageView);
  net.reads.set("/v1/tasks?status=done", { items: [], next_cursor: null } satisfies TaskPageView);
});

afterEach(async () => {
  await act(async () => root.render(null));
});

const refused = () => new ApiError(409, "version_mismatch", "the task changed since it was read", "req-1");

it("says the first tick was refused even after a second tick started", async () => {
  await mount();
  await act(async () => void vm().complete(alpha));
  await act(async () => void vm().complete(beta));
  expect(net.writes.map((w) => `${w.method} ${w.path}`)).toEqual([
    "PATCH /v1/tasks/t1",
    "PATCH /v1/tasks/t2",
  ]);
  await act(async () => {
    net.writes[0]!.reject(refused());
    net.writes[1]!.resolve({ ...beta, status: "done", version: 2 });
  });
  expect(vm().error).toBe(STALE_MESSAGE);
});

it("sends one write for a draft submitted twice before the first answers", async () => {
  await mount();
  const edit = { version: 1, title: "Alpha edited", notes: "", assigneeId: null };
  await act(async () => {
    void vm().save(alpha, edit);
    void vm().save(alpha, edit);
  });
  expect(net.writes).toHaveLength(1);
  expect(vm().saving).toBe(true);
  await act(async () => void net.writes[0]!.resolve({ ...alpha, title: "Alpha edited", version: 2 }));
  expect(vm().saving).toBe(false);
  expect(vm().error).toBeNull();
});
