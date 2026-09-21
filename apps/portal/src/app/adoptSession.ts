// Taking up a new session is one act too: whatever the tab held goes first,
// the token and every answer fetched under it, and only then is the new one
// set. Signing in, signing up, and switching orgs all land here, so no cache
// of the old tenant is ever shown under the new one. The realtime provider
// reopens its socket on the token change.
import type { IssuedSessionView } from "../api";
import { useSessionStore } from "../store/session";
import { forgetSession } from "./forgetSession";

export function adoptSession(issued: Pick<IssuedSessionView, "token" | "org">): void {
  forgetSession();
  useSessionStore.getState().setSession(issued.token, issued.org.slug);
}
