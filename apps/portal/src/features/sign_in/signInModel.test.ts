import type { MembershipChoiceView } from "../../api";
import { describe, expect, it } from "vitest";
import { checkCredentials, chooseOrg, landingPath } from "./signInModel";

const membership = (name: string): MembershipChoiceView => ({
  org: { id: name, name, slug: name.toLowerCase(), created_at: "2026-01-01T00:00:00Z" },
  user: { id: "u", email: "a@b.c", display_name: "A", created_at: "2026-01-01T00:00:00Z" },
  role: "member",
});

describe("checkCredentials", () => {
  it("asks for an email and a password", () => {
    expect(checkCredentials("nope", "x").ok).toBe(false);
    expect(checkCredentials("a@b.c", "").ok).toBe(false);
    expect(checkCredentials("a@b.c", "pw")).toEqual({ ok: true, message: null });
  });
});

describe("chooseOrg", () => {
  it("picks the only org and sorts several by name", () => {
    expect(chooseOrg([])).toEqual({ kind: "none" });
    expect(chooseOrg([membership("Acme")]).kind).toBe("single");
    const several = chooseOrg([membership("Zeta"), membership("Acme")]);
    expect(several.kind === "several" && several.memberships.map((m) => m.org.name)).toEqual([
      "Acme",
      "Zeta",
    ]);
  });
});

describe("where signing in lands", () => {
  it("returns to the page RequireAuth turned away", () => {
    expect(landingPath("/settings")).toBe("/settings");
  });

  it("falls back to the task list when there is nothing to return to", () => {
    expect(landingPath(undefined)).toBe("/");
    expect(landingPath(null)).toBe("/");
    expect(landingPath("")).toBe("/");
    expect(landingPath("/sign-in")).toBe("/");
  });

  it("takes only an in-app absolute path, never a destination from elsewhere", () => {
    expect(landingPath("//evil.example.test")).toBe("/");
    expect(landingPath("https://evil.example.test")).toBe("/");
    expect(landingPath("settings")).toBe("/");
    expect(landingPath({ pathname: "/settings" })).toBe("/");
  });
});
