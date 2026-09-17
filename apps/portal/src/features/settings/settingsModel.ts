// Pure: rows, formatting, and gating predicates for the settings screen.
import type { ApiKeyView, MeView, UserView } from "@tadas/api-client";

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

export function signedInAs(me: MeView | undefined): string {
  if (!me) return "";
  return `Signed in to ${me.org.name} as ${me.user.display_name} (${me.role})`;
}
