// Pure: rows, formatting, and gating predicates for the settings screen.
import type { ApiKeyView, InvitationView, MeView, Role, UserView } from "../../api";

export interface MemberRow {
  id: string;
  name: string;
  email: string;
  joined: string;
}

export type KeyState = "active" | "expired" | "revoked";

export interface ApiKeyRow {
  id: string;
  name: string;
  role: string;
  state: KeyState;
  expires: string;
}

export function formatDate(iso: string): string {
  return iso.slice(0, 10);
}

export function memberRows(users: UserView[]): MemberRow[] {
  return users.map((user) => ({
    id: user.id,
    name: user.display_name,
    email: user.email,
    joined: formatDate(user.created_at),
  }));
}

export function keyState(key: ApiKeyView, now: Date): KeyState {
  if (key.deleted_at) return "revoked";
  if (new Date(key.expires_at).getTime() <= now.getTime()) return "expired";
  return "active";
}

export function apiKeyRows(keys: ApiKeyView[], now: Date): ApiKeyRow[] {
  return keys.map((key) => ({
    id: key.id,
    name: key.name,
    role: key.role,
    state: keyState(key, now),
    expires: formatDate(key.expires_at),
  }));
}

export function canManageKeys(me: MeView | undefined): boolean {
  return me?.permissions.includes("manage_keys") ?? false;
}

export function canManageMembers(me: MeView | undefined): boolean {
  return me?.permissions.includes("manage_members") ?? false;
}

/** Single sign-on is a team org's, set up by a member who manages members. */
export function ssoAvailable(me: MeView | undefined): boolean {
  return canManageMembers(me) && me?.org.kind === "team";
}

const INVITABLE: readonly Role[] = ["viewer", "member", "admin"];
const RANK: Readonly<Record<string, number>> = { viewer: 0, member: 1, admin: 2, owner: 3 };

/** The roles an invitation may carry: never above the caller's own, and
 * never owner, which an org has one of. */
export function invitableRoles(me: MeView | undefined): Role[] {
  if (!me) return [];
  const mine = RANK[me.role] ?? -1;
  return INVITABLE.filter((role) => (RANK[role] ?? 99) <= mine);
}

export interface InvitationRow {
  id: string;
  email: string;
  role: string;
  expires: string;
  expired: boolean;
}

export function invitationRows(invitations: InvitationView[], now: Date): InvitationRow[] {
  return invitations.map((invitation) => ({
    id: invitation.id,
    email: invitation.email,
    role: invitation.role,
    expires: formatDate(invitation.expires_at),
    expired: new Date(invitation.expires_at).getTime() <= now.getTime(),
  }));
}

/** The invite form asks for an address; the server checks the rest. */
export function checkInvite(email: string): string | null {
  return email.trim().includes("@") ? null : "Enter the email address to invite.";
}
