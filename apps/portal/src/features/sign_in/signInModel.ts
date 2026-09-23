// Pure: validation and the org choice. No React, no fetch.
import type { MembershipChoiceView } from "../../api";
import { byPlace } from "../../app/orgChipModel";

export interface CredentialsCheck {
  ok: boolean;
  message: string | null;
}

export function checkCredentials(email: string, password: string): CredentialsCheck {
  if (!email.includes("@")) return { ok: false, message: "Enter the email you signed up with." };
  if (password.length === 0) return { ok: false, message: "Enter your password." };
  return { ok: true, message: null };
}

export type OrgChoice =
  | { kind: "none" }
  | { kind: "single"; membership: MembershipChoiceView }
  | { kind: "several"; memberships: MembershipChoiceView[] };

export function chooseOrg(memberships: MembershipChoiceView[]): OrgChoice {
  const [first] = memberships;
  if (first === undefined) return { kind: "none" };
  if (memberships.length === 1) return { kind: "single", membership: first };
  return { kind: "several", memberships: [...memberships].sort(byPlace) };
}


/** Where to land after signing in: the page RequireAuth turned away, when it
 * named one of ours, and the task list otherwise. What the history state
 * carries is not trusted as a destination; only an in-app absolute path is. */
export function landingPath(from: unknown): string {
  if (typeof from !== "string") return "/";
  if (!from.startsWith("/") || from.startsWith("//") || from === "/sign-in") return "/";
  return from;
}
