import type { MembershipChoiceView } from "../../api";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { useExchangeSession, useLogin } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { useSessionStore } from "../../store/session";
import { checkCredentials, chooseOrg, landingPath, type OrgChoice } from "./signInModel";

export function useSignInVm() {
  const navigate = useNavigate();
  const location = useLocation();
  const setSession = useSessionStore((s) => s.setSession);
  const notify = useNoticesStore((s) => s.notify);
  const login = useLogin();
  const exchange = useExchangeSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loginToken, setLoginToken] = useState<string | null>(null);
  const [choice, setChoice] = useState<OrgChoice>({ kind: "none" });

  const enter = async (token: string, membership: MembershipChoiceView) => {
    const issued = await exchange.mutateAsync({ loginToken: token, body: { org_id: membership.org.id } });
    setSession(issued.token, issued.org.slug);
    navigate(landingPath((location.state as { from?: unknown } | null)?.from), { replace: true });
  };

  const submit = async () => {
    setError(null);
    const check = checkCredentials(email, password);
    if (!check.ok) {
      setError(check.message);
      return;
    }
    try {
      const issued = await login.mutateAsync({ email, password });
      const next = chooseOrg(issued.memberships);
      setLoginToken(issued.token);
      setChoice(next);
      if (next.kind === "single") await enter(issued.token, next.membership);
      if (next.kind === "none") setError("This account belongs to no organization yet.");
    } catch (caught) {
      setError(errorMessage(caught, "Sign-in failed."));
    }
  };

  // Choosing an org can be refused too (the login token expired, the API is
  // away); the refusal is said the same way a failed write is.
  const pick = async (membership: MembershipChoiceView) => {
    if (!loginToken) return;
    try {
      await enter(loginToken, membership);
    } catch (caught) {
      notify(errorMessage(caught, "Sign-in failed."));
    }
  };

  return {
    email,
    password,
    error,
    choice,
    busy: login.isPending || exchange.isPending,
    setEmail,
    setPassword,
    submit,
    pick,
  };
}
