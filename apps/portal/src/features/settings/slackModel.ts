// Pure: what the Slack section of the settings screen says, and who may act
// on it. The org has one channel at most; linking one is a code typed in it.
import type { IssuedSlackLinkCodeView, MeView, SlackConnectionView, SlackStatusView } from "../../api";

export const INVITE_COMMAND = "/invite @tadas";

export type SlackState = "not_connected" | "connected" | "broken";

export interface SlackSummary {
  state: SlackState;
  /** One line on the connection. */
  line: string;
  /** What to do about a broken connection, in plain words; null otherwise. */
  fix: string | null;
  /** The label of the button that issues a code. */
  connectLabel: string;
}

export interface IssuedCode {
  code: string;
  expiresAt: string;
  /** The connection as it stood when the code was issued, to tell when it was used. */
  connectionAtIssue: Pick<SlackConnectionView, "id" | "updated_at"> | null;
}

/** Linking and disconnecting take an owner or an admin: the API refuses anyone else. */
export function canManageSlack(me: MeView | undefined): boolean {
  return me?.permissions.includes("manage_members") ?? false;
}

export function brokenReasonText(reason: string | null): string {
  switch (reason) {
    case "not_in_channel":
      return `@tadas is not in the channel: type ${INVITE_COMMAND} in it, then link again.`;
    case "channel_not_found":
    case "is_archived":
      return "The channel was deleted or archived: link another.";
    default:
      return reason
        ? `Slack refuses posts to the channel (${reason}): link it again, or link another.`
        : "Slack refuses posts to the channel: link it again, or link another.";
  }
}

export function slackSummary(status: SlackStatusView | undefined): SlackSummary {
  const connection = status?.connection ?? null;
  if (!connection) {
    return { state: "not_connected", line: "Not connected.", fix: null, connectLabel: "Connect Slack" };
  }
  if (connection.status === "broken") {
    return {
      state: "broken",
      line: `Connected to channel ${connection.channel_id}, but posts to it fail.`,
      fix: brokenReasonText(connection.broken_reason),
      connectLabel: "Link another channel",
    };
  }
  return {
    state: "connected",
    line: `Connected to channel ${connection.channel_id}.`,
    fix: null,
    connectLabel: "Link another channel",
  };
}

/** HH:MM in the browser's local time. */
export function clockOf(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function linkCommand(code: string): string {
  return `/tadas link ${code}`;
}

/** The code the server issued, or null when the answer lost it on the way. */
export function issuedCode(issued: IssuedSlackLinkCodeView, status: SlackStatusView | undefined): IssuedCode | null {
  if (!issued.code) return null;
  const connection = status?.connection ?? null;
  return {
    code: issued.code,
    expiresAt: issued.expires_at,
    connectionAtIssue: connection && { id: connection.id, updated_at: connection.updated_at },
  };
}

/** A code stops being shown once the connection moved on from where it stood
 * when the code was issued: the code was used, or another one was. */
export function codeStillPending(code: IssuedCode, status: SlackStatusView | undefined): boolean {
  const now = status?.connection ?? null;
  const then = code.connectionAtIssue;
  if (!now) return then === null;
  return then !== null && now.id === then.id && now.updated_at === then.updated_at;
}
