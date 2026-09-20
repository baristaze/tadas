// The sign-out as one flow with its effects handed in, so it runs in a test
// without React: the server session is revoked while the token is still
// held, and the session is forgotten here whatever the server said. A 401
// means the session was gone already; any other refusal is said, since the
// server session may outlive the sign-out until it expires.
import { ApiError } from "../../api";
import { errorMessage } from "../../app/errorMessage";

export const NOT_REVOKED_MESSAGE = "Signed out here; the server did not revoke the session.";

export interface SignOutEffects {
  /** The logout call, made with the token the session still holds. */
  revoke: () => Promise<unknown>;
  /** Drops the token and everything fetched under it. */
  forget: () => void;
  /** Says what went wrong in one line. */
  report: (message: string) => void;
}

export type SignOutOutcome = "revoked" | "already_gone" | "not_revoked";

/** The server no longer knows the session: there was nothing left to revoke. */
export function isAlreadyGone(cause: unknown): boolean {
  return cause instanceof ApiError && cause.status === 401;
}

export async function signOut(effects: SignOutEffects): Promise<SignOutOutcome> {
  let outcome: SignOutOutcome = "revoked";
  try {
    await effects.revoke();
  } catch (cause) {
    outcome = isAlreadyGone(cause) ? "already_gone" : "not_revoked";
    if (outcome === "not_revoked") effects.report(errorMessage(cause, NOT_REVOKED_MESSAGE));
  } finally {
    effects.forget();
  }
  return outcome;
}
