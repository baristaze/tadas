import type { MeView, SlackConnectionView, SlackStatusView } from "../../api";
import { describe, expect, it } from "vitest";
import {
  brokenReasonText,
  canManageSlack,
  clockOf,
  codeStillPending,
  issuedCode,
  linkCommand,
  slackSummary,
} from "./slackModel";

const connection = (overrides: Partial<SlackConnectionView> = {}): SlackConnectionView => ({
  id: "c1",
  team_id: "T1",
  channel_id: "C0123",
  status: "ok",
  broken_reason: null,
  created_by: "u1",
  created_at: "2026-09-22T10:00:00Z",
  updated_at: "2026-09-22T10:00:00Z",
  ...overrides,
});

const status = (c: SlackConnectionView | null): SlackStatusView => ({ connection: c });

const me = (permissions: MeView["permissions"]): MeView => ({
  user: { id: "u1", email: "a@b.c", display_name: "Ann", created_at: "2026-09-01T00:00:00Z" },
  org: { id: "o1", name: "Acme", slug: "acme", kind: "team", created_at: "2026-09-01T00:00:00Z" },
  role: "member",
  permissions,
  app: "portal",
});

// A local moment, so the clock reads the same in any zone the test runs in.
const expires = new Date(2026, 8, 22, 14, 5).toISOString();

describe("slack model", () => {
  it("lets an owner or an admin link and disconnect, and a member only look", () => {
    expect(canManageSlack(me(["read", "write", "manage_members"]))).toBe(true);
    expect(canManageSlack(me(["read", "write"]))).toBe(false);
    expect(canManageSlack(undefined)).toBe(false);
  });

  it("says the state of the connection", () => {
    expect(slackSummary(undefined)).toMatchObject({ state: "not_connected", line: "Not connected.", fix: null });
    expect(slackSummary(status(null)).connectLabel).toBe("Connect Slack");
    expect(slackSummary(status(connection()))).toEqual({
      state: "connected",
      line: "Connected to channel C0123.",
      fix: null,
      connectLabel: "Link another channel",
    });
    expect(slackSummary(status(connection({ status: "broken", broken_reason: "not_in_channel" })))).toEqual({
      state: "broken",
      line: "Connected to channel C0123, but posts to it fail.",
      fix: "@tadas is not in the channel: type /invite @tadas in it, then link again.",
      connectLabel: "Link another channel",
    });
  });

  it("puts each refusal in plain words", () => {
    expect(brokenReasonText("channel_not_found")).toBe("The channel was deleted or archived: link another.");
    expect(brokenReasonText("is_archived")).toBe("The channel was deleted or archived: link another.");
    expect(brokenReasonText("token_revoked")).toBe(
      "Slack refuses posts to the channel (token_revoked): link it again, or link another.",
    );
    expect(brokenReasonText(null)).toBe("Slack refuses posts to the channel: link it again, or link another.");
  });

  it("says how to use a code and when it expires", () => {
    expect(clockOf(expires)).toBe("14:05");
    expect(linkCommand("ABCD-EFGH")).toBe("/tadas link ABCD-EFGH");
    expect(clockOf("not a time")).toBe("");
  });

  it("keeps a code until the connection moves on from where it stood", () => {
    const fresh = issuedCode({ code: "ABCD-EFGH", expires_at: expires }, status(null))!;
    expect(fresh.connectionAtIssue).toBeNull();
    expect(codeStillPending(fresh, status(null))).toBe(true);
    expect(codeStillPending(fresh, status(connection()))).toBe(false);

    const relink = issuedCode({ code: "WXYZ-2345", expires_at: expires }, status(connection()))!;
    expect(codeStillPending(relink, status(connection()))).toBe(true);
    expect(codeStillPending(relink, status(connection({ updated_at: "2026-09-22T11:00:00Z" })))).toBe(false);
    expect(codeStillPending(relink, status(connection({ id: "c2" })))).toBe(false);
    expect(codeStillPending(relink, status(null))).toBe(false);
  });

  it("has no code to show when the answer lost it", () => {
    expect(issuedCode({ code: null, expires_at: expires }, status(null))).toBeNull();
  });
});
