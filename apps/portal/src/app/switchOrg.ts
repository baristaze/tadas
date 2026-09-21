// The switch as one flow with its effects handed in, so it runs in a test
// without React. The exchange is presented with the session this tab holds,
// so it goes first, while that token is still held; the server ends that
// session in the same write. Only then is the old tenant dropped (the
// token, every cached answer) and the new session taken up. A refusal leaves
// the tab where it was: a 401 has already signed the tab out through the
// client, and anything else is said.
import { ApiError, type IssuedSessionView } from "../api";
import { errorMessage } from "./errorMessage";

export interface SwitchEffects {
  /** The exchange, presented with the current session and the chosen org. */
  exchange: () => Promise<IssuedSessionView>;
  /** Drops the old tenant and takes up the new session. */
  adopt: (issued: IssuedSessionView) => void;
  /** Says what went wrong in one line. */
  report: (message: string) => void;
}

export type SwitchOutcome = "switched" | "signed_out" | "refused";

export async function switchOrg(effects: SwitchEffects): Promise<SwitchOutcome> {
  let issued: IssuedSessionView;
  try {
    issued = await effects.exchange();
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 401) return "signed_out";
    effects.report(errorMessage(cause, "Switching organizations failed."));
    return "refused";
  }
  effects.adopt(issued);
  return "switched";
}
