// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { TaskView } from "../../api";
import { TaskItem } from "./TaskItem";
import { taskRow } from "./tasksModel";

// The attachments panel reads its own queries; this case is about the draft.
vi.mock("../attachments/Attachments", () => ({
  Attachments: ({ canWrite }: { canWrite: boolean }) => createElement("aside", { "data-can-write": String(canWrite) }),
}));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
const container = document.createElement("div");
document.body.append(container);
const root = createRoot(container);
afterEach(async () => { await act(async () => root.render(null)); });

it("keeps an unsaved draft and its original version through a realtime refresh", async () => {
  const task: TaskView = {
    id: "t1", title: "Original", notes: "", status: "open", assignee_id: null,
    position: 0, version: 1, created_by: "u1", deleted_at: null, remind_at: null, reminded_at: null,
    created_at: "2026-09-20T10:00:00Z", updated_at: "2026-09-20T10:00:00Z",
  };
  const onSave = vi.fn();
  const render = (current: TaskView, editing = true) => act(async () => {
    root.render(createElement(TaskItem, {
      task: current, row: taskRow(current, new Map(), "u1"), leaving: false,
      listMountedAt: Date.now(), canWrite: true, editing, saving: false,
      assigneeOptions: [{ value: "", label: "Unassigned" }],
      onToggle: vi.fn(), onEdit: vi.fn(), onCancelEdit: vi.fn(), onDelete: vi.fn(), onSave,
    }));
  });
  await render(task);
  const title = container.querySelector("input[type=text]") as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(title, "My draft");
    title.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const updated = { ...task, title: "Remote edit", version: 2, updated_at: "2026-09-20T10:01:00Z" };
  await render(updated);
  expect((container.querySelector("input[type=text]") as HTMLInputElement).value).toBe("My draft");
  await act(async () => {
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(onSave).toHaveBeenLastCalledWith({ title: "My draft", notes: "", assigneeId: null, version: 1 });
  // Closing and reopening explicitly starts a fresh edit of the current row.
  await render(updated, false);
  await render(updated);
  expect((container.querySelector("input[type=text]") as HTMLInputElement).value).toBe("Remote edit");
});

it("holds the Save button while the save it started is in flight", async () => {
  const task: TaskView = {
    id: "t2", title: "Original", notes: "", status: "open", assignee_id: null,
    position: 0, version: 1, created_by: "u1", deleted_at: null, remind_at: null, reminded_at: null,
    created_at: "2026-09-20T10:00:00Z", updated_at: "2026-09-20T10:00:00Z",
  };
  const render = (saving: boolean) => act(async () => {
    root.render(createElement(TaskItem, {
      task, row: taskRow(task, new Map(), "u1"), leaving: false,
      listMountedAt: Date.now(), canWrite: true, editing: true, saving,
      assigneeOptions: [{ value: "", label: "Unassigned" }],
      onToggle: vi.fn(), onEdit: vi.fn(), onCancelEdit: vi.fn(), onDelete: vi.fn(), onSave: vi.fn(),
    }));
  });
  const save = () => container.querySelector("button[type=submit]") as HTMLButtonElement;
  await render(false);
  expect(save().disabled).toBe(false);
  await render(true);
  expect(save().disabled).toBe(true);
});

it("leads with the drag handle, keeps one line, and names the creator without a marker", async () => {
  const task: TaskView = {
    id: "t3", title: "Migrate DB", notes: "", status: "open", assignee_id: "u1",
    position: 0, version: 1, created_by: "u1", deleted_at: null, remind_at: null, reminded_at: null,
    created_at: "2026-09-20T10:00:00Z", updated_at: "2026-09-20T10:00:00Z",
  };
  const onEdit = vi.fn();
  const drag = {
    draggable: false, dragging: false, dropIndicator: null, onGrab: vi.fn(),
    onDragStart: vi.fn(), onDragOver: vi.fn(), onDrop: vi.fn(), onDragEnd: vi.fn(),
  };
  await act(async () => {
    root.render(createElement(TaskItem, {
      task, row: taskRow(task, new Map(), "u1"), leaving: false,
      listMountedAt: Date.now(), canWrite: true, editing: false, saving: false,
      assigneeOptions: [{ value: "", label: "Unassigned" }], drag,
      onToggle: vi.fn(), onEdit, onCancelEdit: vi.fn(), onDelete: vi.fn(), onSave: vi.fn(),
    }));
  });
  const line = container.querySelector("li > div") as HTMLElement;
  const [handle, box, title] = [...line.children] as HTMLElement[];
  expect(handle!.getAttribute("aria-label")).toBe("Drag to reorder Migrate DB");
  expect(box!.getAttribute("type")).toBe("checkbox");
  expect(title!.textContent).toBe("Migrate DB");
  expect(title!.style.whiteSpace).toBe("nowrap");
  expect(line.style.flexWrap).toBe("");
  const pills = [...line.querySelectorAll("span[title]")].map((pill) => pill.textContent);
  expect(pills).toContain("you");
  expect(pills).toContain("for you");
  await act(async () => title!.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })));
  expect(onEdit).toHaveBeenCalledOnce();
});

it("lets someone who cannot write open a task's files, read-only, with no edit form", async () => {
  const task: TaskView = {
    id: "t1", title: "Read only", notes: "", status: "open", assignee_id: null,
    position: 0, version: 1, created_by: "u1", deleted_at: null,
    created_at: "2026-09-20T10:00:00Z", updated_at: "2026-09-20T10:00:00Z",
  };
  await act(async () => {
    root.render(createElement(TaskItem, {
      task, row: taskRow(task, new Map(), "u1"), leaving: false,
      listMountedAt: Date.now(), canWrite: false, editing: false, saving: false,
      assigneeOptions: [],
      onToggle: vi.fn(), onEdit: vi.fn(), onCancelEdit: vi.fn(), onDelete: vi.fn(), onSave: vi.fn(),
    }));
  });
  expect(container.querySelector("aside")).toBeNull();
  const files = [...container.querySelectorAll("button")].find((b) => b.textContent === "files")!;
  await act(async () => files.click());
  expect(container.querySelector("aside")!.dataset.canWrite).toBe("false");
  expect(container.querySelector("form")).toBeNull();
});

it("shows the due time on the row and sends a changed or cleared one from the edit", async () => {
  const soon = new Date(Date.now() + 3_600_000);
  const task: TaskView = {
    id: "t4", title: "Call the bank", notes: "", status: "open", assignee_id: null,
    position: 0, version: 5, created_by: "u1", deleted_at: null,
    remind_at: soon.toISOString(), reminded_at: null,
    created_at: "2026-09-20T10:00:00Z", updated_at: "2026-09-20T10:00:00Z",
  };
  const onSave = vi.fn();
  const render = (current: TaskView, editing: boolean) => act(async () => {
    root.render(createElement(TaskItem, {
      task: current, row: taskRow(current, new Map(), "u1"), leaving: false,
      listMountedAt: Date.now(), canWrite: true, editing, saving: false,
      assigneeOptions: [{ value: "", label: "Unassigned" }],
      onToggle: vi.fn(), onEdit: vi.fn(), onCancelEdit: vi.fn(), onDelete: vi.fn(), onSave,
    }));
  });
  await render(task, false);
  const badge = () => [...container.querySelectorAll("li > div span[title]")].find((pill) => pill.getAttribute("title")!.startsWith("Due "));
  expect(badge()!.textContent).toMatch(/^due \S+ \d{2}:\d{2}$/);
  await render({ ...task, reminded_at: soon.toISOString() }, false);
  expect(badge()!.textContent).toMatch(/^reminded /);
  expect(badge()!.getAttribute("title")).toMatch(/The reminder went out\.$/);

  await render(task, true);
  const submit = () => act(async () => {
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  // Unchanged: the field is left out, so the due time is kept.
  await submit();
  expect(onSave.mock.lastCall![0]).not.toHaveProperty("remindAt");
  const input = container.querySelector("input[type=datetime-local]") as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "2030-01-02T08:15");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await submit();
  expect(new Date(onSave.mock.lastCall![0].remindAt).getTime()).toBe(new Date(2030, 0, 2, 8, 15).getTime());
  const clear = [...container.querySelectorAll("button")].find((b) => b.textContent === "clear due time")!;
  await act(async () => clear.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await submit();
  expect(onSave.mock.lastCall![0]).toMatchObject({ remindAt: null, version: 5 });
});
