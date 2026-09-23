// Pure: what a sign-up asks for and what a refusal says. No React, no fetch.
// The server decides; these checks only save a round trip on what it would
// refuse anyway. A sign-up asks nothing about an org: the person's personal
// org comes with them, named and slugged by the server.
import { ApiError } from "../../api";
import { errorMessage } from "../../app/errorMessage";

export const MIN_PASSWORD_LENGTH = 8;

export interface SignUpForm {
  email: string;
  displayName: string;
  password: string;
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
  return { ok: true, message: null };
}

/** A held email is said as a pointer to sign-in; everything else the way every screen says a failure. */
export function signUpRefusal(caught: unknown, fallback: string): { message: string; signIn: boolean } {
  if (caught instanceof ApiError && caught.status === 409 && /email/.test(caught.message))
    return { message: "An account with this email exists. Sign in instead.", signIn: true };
  if (caught instanceof ApiError && caught.status === 404)
    return { message: "Sign-up is closed here. Ask an owner to add you.", signIn: false };
  return { message: errorMessage(caught, fallback), signIn: false };
}
