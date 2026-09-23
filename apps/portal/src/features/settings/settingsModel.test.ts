import type { ApiKeyView, InvitationView, MeView } from "../../api";
import { describe, expect, it } from "vitest";
import {
  apiKeyRows,
  canManageKeys,
  canManageMembers,
  checkInvite,
  invitableRoles,
  invitationRows,
  keyState,
  memberRows,
  signedInAs,
  ssoAvailable,
} from "./settingsModel";

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
  org: { id: "o1", name: "Acme", slug: "acme", kind: "team", created_at: "2026-09-01T00:00:00Z" },
  role: "owner",
  permissions: ["read", "write", "manage_members", "manage_keys"],
  app: "portal",
};

describe("settings model", () => {
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
    expect(signedInAs(undefined)).toBe("");
    expect(signedInAs(me)).toBe("Signed in to Acme as Ann (owner)");
  });
});

describe("members and single sign-on", () => {
  const as = (role: MeView["role"], permissions: MeView["permissions"], kind: "team" | "personal" = "team"): MeView => ({
    ...me,
    role,
    permissions,
    org: { ...me.org, kind },
  });

  it("lets a member who manages members invite and open single sign-on on a team org", () => {
    expect(canManageMembers(me)).toBe(true);
    expect(canManageMembers(as("member", ["read", "write"]))).toBe(false);
    expect(canManageMembers(undefined)).toBe(false);
    expect(ssoAvailable(me)).toBe(true);
    expect(ssoAvailable(as("owner", me.permissions, "personal"))).toBe(false);
    expect(ssoAvailable(as("member", ["read", "write"]))).toBe(false);
  });

  it("offers the roles up to the caller's own and never owner", () => {
    expect(invitableRoles(me)).toEqual(["viewer", "member", "admin"]);
    expect(invitableRoles(as("admin", me.permissions))).toEqual(["viewer", "member", "admin"]);
    expect(invitableRoles(as("member", me.permissions))).toEqual(["viewer", "member"]);
    expect(invitableRoles(undefined)).toEqual([]);
  });

  it("lists pending invitations with their expiry", () => {
    const invitation = (expires_at: string): InvitationView => ({
      id: "i1",
      email: "bob@example.test",
      role: "member",
      state: "pending",
      expires_at,
      created_at: "2026-09-10T00:00:00Z",
      created_by: "u1",
    });
    expect(invitationRows([invitation("2026-09-20T00:00:00Z")], now)).toEqual([
      { id: "i1", email: "bob@example.test", role: "member", expires: "2026-09-20", expired: false },
    ]);
    expect(invitationRows([invitation("2026-09-15T00:00:00Z")], now)[0]?.expired).toBe(true);
  });

  it("asks for an address to invite", () => {
    expect(checkInvite("bob")).not.toBeNull();
    expect(checkInvite(" bob@example.test ")).toBeNull();
  });
});
