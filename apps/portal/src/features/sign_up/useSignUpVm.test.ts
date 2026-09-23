// @vitest-environment jsdom
// The sign-up form over a fake transport: it sends an email, a name, and a
// password and nothing about an org, then exchanges the sign-in it gets for
// a session in the one place it names, the person's personal org.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { IssuedLoginView, IssuedSessionView } from "../../api";
import { useSessionStore } from "../../store/session";
import { useSignUpVm } from "./useSignUpVm";

const net = vi.hoisted(() => {
  const sent: { path: string; body: unknown; options: unknown }[] = [];
  const answers = new Map<string, unknown>();
  const post = (path: string, body: unknown, options?: unknown) => {
    sent.push({ path, body, options });
    return answers.has(path) ? Promise.resolve(answers.get(path)) : Promise.reject(new Error(path));
  };
  const navigate = vi.fn();
  return { sent, answers, post, navigate };
});

vi.mock("../../app/api", () => ({ api: { post: net.post } }));
vi.mock("react-router-dom", () => ({ useNavigate: () => net.navigate }));

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
let root: ReturnType<typeof createRoot>;

const org = { id: "p1", name: "Dee", slug: "dee-1a2b3c4d", kind: "personal" as const, created_at: "2026-09-01T00:00:00Z" };
const user = { id: "u1", email: "dee@example.test", display_name: "Dee", created_at: "2026-09-01T00:00:00Z" };
const login: IssuedLoginView = {
  token: "lgn_1",
  expires_at: "2026-09-01T00:10:00Z",
  memberships: [{ org, user, role: "owner" }],
};
const session: IssuedSessionView = { token: "ses_1", expires_at: "2026-09-02T00:00:00Z", org, user, role: "owner" };

const held: { vm?: ReturnType<typeof useSignUpVm> } = {};
const vm = () => held.vm!;

function Probe() {
  const current = useSignUpVm();
  useEffect(() => {
    held.vm = current;
  });
  return null;
}

beforeEach(() => {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  net.sent.length = 0;
  net.answers.clear();
  net.navigate.mockReset();
  useSessionStore.getState().clear();
});

afterEach(async () => {
  await act(async () => root.render(null));
});

it("asks for no org and lands the person in their personal org", async () => {
  net.answers.set("/v1/auth/signup", login);
  net.answers.set("/v1/auth/sessions", session);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(createElement(QueryClientProvider, { client: queryClient }, createElement(Probe)));
  });
  expect(Object.keys(vm())).not.toContain("orgName");
  expect(Object.keys(vm())).not.toContain("orgSlug");
  await act(async () => {
    vm().setEmail("dee@example.test");
    vm().setDisplayName(" Dee ");
    vm().setPassword("long-enough");
  });
  await act(async () => vm().submit());
  expect(net.sent.map((s) => [s.path, s.body])).toEqual([
    ["/v1/auth/signup", { email: "dee@example.test", password: "long-enough", display_name: "Dee" }],
    ["/v1/auth/sessions", { org_id: "p1" }],
  ]);
  expect(useSessionStore.getState().token).toBe("ses_1");
  expect(net.navigate).toHaveBeenCalledWith("/", { replace: true });
});
