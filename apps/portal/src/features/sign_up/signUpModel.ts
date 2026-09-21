// Pure: what a sign-up asks for, the slug it suggests, and what a refusal
// says. No React, no fetch. The server decides; these checks only save a
// round trip on what it would refuse anyway.
import { ApiError } from "../../api";
import { errorMessage } from "../../app/errorMessage";

export const MIN_PASSWORD_LENGTH = 8;
export const MAX_SLUG_LENGTH = 48;
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export interface SignUpForm {
  email: string;
  displayName: string;
  password: string;
  orgName: string;
  orgSlug: string;
}

export interface SignUpCheck {
  ok: boolean;
  message: string | null;
}

export function checkSignUp(form: SignUpForm): SignUpCheck {
  const [local, domain] = form.email.split("@");
  if (!local || !domain || !domain.includes(".") || form.email.split("@").length !== 2)
    return { ok: false, message: "Enter your email address." };
  if (!form.displayName.trim()) return { ok: false, message: "Enter the name people see." };
  if (form.password.length < MIN_PASSWORD_LENGTH)
    return { ok: false, message: `A password has at least ${MIN_PASSWORD_LENGTH} characters.` };
  if (!form.orgName.trim()) return { ok: false, message: "Name your organization." };
  if (!isSlug(form.orgSlug))
    return {
      ok: false,
      message: "The short name is lower-case letters and digits joined by hyphens.",
    };
  return { ok: true, message: null };
}

export function isSlug(slug: string): boolean {
  return slug.length <= MAX_SLUG_LENGTH && SLUG.test(slug);
}

/** The short name suggested for an org's name: lower-case ASCII letters and
 * digits, every other run as one hyphen, trimmed. The person may change it. */
export function suggestSlug(orgName: string): string {
  return orgName
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MAX_SLUG_LENGTH)
    .replace(/-+$/g, "");
}

/** The slug field follows the org's name until the person types in it. */
export function slugAfterNameChange(orgName: string, slug: string, edited: boolean): string {
  return edited ? slug : suggestSlug(orgName);
}

/** A held email is said as a pointer to sign-in; everything else the way every screen says a failure. */
export function signUpRefusal(caught: unknown, fallback: string): { message: string; signIn: boolean } {
  if (caught instanceof ApiError && caught.status === 409 && /email/.test(caught.message))
    return { message: "An account with this email exists. Sign in instead.", signIn: true };
  if (caught instanceof ApiError && caught.status === 404)
    return { message: "Sign-up is closed here. Ask an owner to add you.", signIn: false };
  return { message: errorMessage(caught, fallback), signIn: false };
}
