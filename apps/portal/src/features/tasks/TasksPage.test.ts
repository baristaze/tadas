// @vitest-environment jsdom
// Quick creation is one text box: the title, then Enter or Add. The view
// model is stubbed; this case is about the form the page draws.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TasksPage } from "./TasksPage";

const vm = vi.hoisted(() => ({
  scope: "mine",
  setScope: () => undefined,
  title: "Call the bank",
  setTitle: () => undefined,
  add: vi.fn(() => Promise.resolve()),
  adding: false,
  canWrite: true,
  loading: true,
  error: null,
}));

vi.mock("./useTasksVm", () => ({ useTasksVm: () => vm }));
vi.mock("../../app/AppNav", () => ({ AppNav: () => null }));
vi.mock("./TaskItem", () => ({ TaskItem: () => null }));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

let root: ReturnType<typeof createRoot>;
const container = document.createElement("div");
document.body.append(container);

beforeEach(async () => {
  vm.add.mockClear();
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
