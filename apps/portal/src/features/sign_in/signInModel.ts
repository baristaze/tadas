// Pure: validation and the org choice. No React, no fetch.
import type { MembershipChoiceView } from "../../api";

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
  return { kind: "several", memberships: [...memberships].sort((a, b) => a.org.name.localeCompare(b.org.name)) };
}
