// @vitest-environment jsdom
// Quick creation is one text box: the title, then Enter or Add. The import
// is an action of its own, outside that form. The view models are stubbed;
// this case is about what the page draws.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TasksPage } from "./TasksPage";

const vm = vi.hoisted(() => ({
  scope: "mine",
  orgKind: "team" as "team" | "personal",
  setScope: vi.fn(),
  title: "Call the bank",
  setTitle: () => undefined,
  add: vi.fn(() => Promise.resolve()),
  adding: false,
  canWrite: true,
  loading: true,
  error: null,
}));

const imports = vi.hoisted(() => ({
  canImport: true,
  dialogOpen: false,
  openDialog: vi.fn(),
  closeDialog: () => undefined,
  picked: null,
  pick: () => undefined,
  starting: false,
  failure: null,
  start: () => Promise.resolve(),
  shown: null,
}));

vi.mock("./useTasksVm", () => ({ useTasksVm: () => vm }));
vi.mock("../imports/useImportVm", () => ({ useImportVm: () => imports }));
vi.mock("../../app/AppNav", () => ({ AppNav: () => null }));
vi.mock("../billing/PaymentNotice", () => ({ PaymentNotice: () => null }));
vi.mock("./TaskItem", () => ({ TaskItem: () => null }));
vi.mock("./ArchivedTasks", () => ({ ArchivedTasks: () => null }));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

let root: ReturnType<typeof createRoot>;
const container = document.createElement("div");
document.body.append(container);

beforeEach(async () => {
  vm.add.mockClear();
  vm.setScope.mockClear();
  vm.orgKind = "team";
  root = createRoot(container);
  await act(async () => root.render(createElement(TasksPage)));
});
afterEach(async () => { await act(async () => root.render(null)); });

it("draws one text box and the Add button, and no date field", () => {
  const form = container.querySelector("form")!;
  const inputs = [...form.querySelectorAll("input")];
  expect(inputs.map((input) => input.getAttribute("aria-label"))).toEqual(["New task"]);
  expect(form.querySelector("input[type=date], input[type=datetime-local]")).toBeNull();
  expect(form.querySelector("button[type=submit]")!.textContent).toBe("Add");
});

it("creates on Enter in the text box", async () => {
  const input = container.querySelector("input[aria-label='New task']") as HTMLInputElement;
  // Enter in a form's only text box submits the form: the browser's implicit
  // submission, which jsdom leaves to the page, so the test does what it does.
  await act(async () => {
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    input.form!.requestSubmit();
  });
  expect(vm.add).toHaveBeenCalledOnce();
});

it("creates on a click of Add", async () => {
  const add = container.querySelector("button[type=submit]") as HTMLButtonElement;
  await act(async () => add.click());
  expect(vm.add).toHaveBeenCalledOnce();
});

it("offers the import beside the lists, never inside the quick-add box", async () => {
  const form = container.querySelector("form")!;
  const importButton = [...container.querySelectorAll("button")].find((b) => b.textContent === "Import")!;
  expect(importButton).toBeDefined();
  expect(form.contains(importButton)).toBe(false);
  await act(async () => importButton.click());
  expect(imports.openDialog).toHaveBeenCalledOnce();
});

it("has no Tasks title: in a team org the switch is the heading", async () => {
  expect([...container.querySelectorAll("h1")].map((h) => h.textContent)).toEqual(["My tasks"]);
  expect(container.querySelector("h1")!.className).toBe("tadas-sr-only");
  const choices = [...container.querySelectorAll("[role='radiogroup'] [role='radio']")];
  expect(choices.map((c) => [c.textContent, c.getAttribute("aria-checked")])).toEqual([
    ["My tasks", "true"],
    ["Team", "false"],
  ]);
  await act(async () => (choices[1] as HTMLButtonElement).click());
  expect(vm.setScope).toHaveBeenCalledWith("team");
});

it("in a personal org says My tasks, with no switch", async () => {
  vm.orgKind = "personal";
  await act(async () => root.render(createElement(TasksPage)));
  const heading = container.querySelector("h1")!;
  expect(heading.textContent).toBe("My tasks");
  expect(heading.className).toBe("tadas-title");
  expect(container.querySelector("[role='radiogroup']")).toBeNull();
  expect([...container.querySelectorAll("button")].some((b) => b.textContent === "Import")).toBe(true);
});
