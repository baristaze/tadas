// Forgetting a session is one act: the token goes, and with it everything
// fetched under it, so the next person to sign in on this tab never sees the
// last one's answers. Every path that drops a session goes through here: the
// sign-out, a 401 from the API, a 4401 close of the realtime socket, and a
// sign-in over a tab that still holds one.
import { useSessionStore } from "../store/session";
import { queryClient } from "./queryClient";

export function forgetSession(): void {
  useSessionStore.getState().clear();
  queryClient.clear();
}

/** A refusal that belongs to a token the tab no longer holds says nothing
 * about the session it holds now: a switch ends the old session, and the
 * old socket's close can arrive after the new session is set. */
export function forgetSessionIfHeld(token: string): void {
  if (useSessionStore.getState().token === token) forgetSession();
}
