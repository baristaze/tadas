import type { MembershipChoiceView } from "@tadas/api-client";
import { describe, expect, it } from "vitest";
import { checkCredentials, chooseOrg } from "./signInModel";

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
