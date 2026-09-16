import type { ApiKeyView, MeView } from "@tadas/api-client";
import { describe, expect, it } from "vitest";
import { apiKeyRows, canManageKeys, headline, keyState, memberRows } from "./homeModel";

const now = new Date("2026-09-16T12:00:00Z");

const key = (overrides: Partial<ApiKeyView>): ApiKeyView => ({
  id: "k1",
  name: "ci",
  role: "member",
  user_id: "u1",
  created_at: "2026-09-01T00:00:00Z",
  expires_at: "2026-12-01T00:00:00Z",
  deleted_at: null,
  ...overrides,
});

const me: MeView = {
  user: { id: "u1", email: "a@b.c", display_name: "Ann", created_at: "2026-09-01T00:00:00Z" },
  org: { id: "o1", name: "Acme", slug: "acme", created_at: "2026-09-01T00:00:00Z" },
  role: "owner",
  permissions: ["read", "write", "manage_members", "manage_keys"],
  app: "portal",
};

describe("home model", () => {
  it("derives the key state from revocation and expiry", () => {
    expect(keyState(key({}), now)).toBe("active");
    expect(keyState(key({ expires_at: "2026-09-01T00:00:00Z" }), now)).toBe("expired");
    expect(keyState(key({ deleted_at: "2026-09-10T00:00:00Z" }), now)).toBe("revoked");
  });

  it("builds rows with short dates", () => {
    expect(apiKeyRows([key({})], now)).toEqual([
      { id: "k1", name: "ci", role: "member", state: "active", expires: "2026-12-01" },
    ]);
    expect(memberRows([me.user])).toEqual([
      { id: "u1", name: "Ann", email: "a@b.c", joined: "2026-09-01" },
    ]);
  });

  it("gates key management on the permission", () => {
    expect(canManageKeys(me)).toBe(true);
    expect(canManageKeys({ ...me, permissions: ["read"] })).toBe(false);
    expect(canManageKeys(undefined)).toBe(false);
    expect(headline(undefined)).toBe("Loading your workspace");
    expect(headline(me)).toBe("Acme");
  });
});
