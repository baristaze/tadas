import { ApiError, type MembershipChoiceView } from "@tadas/api-client";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useExchangeSession, useLogin } from "../../queries/tenancy";
import { useSessionStore } from "../../store/session";
import { checkCredentials, chooseOrg, type OrgChoice } from "./signInModel";

export function useSignInVm() {
  const navigate = useNavigate();
  const setSession = useSessionStore((s) => s.setSession);
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
    navigate("/", { replace: true });
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
      setError(caught instanceof ApiError ? `${caught.message} (${caught.requestId ?? "no id"})` : "Sign-in failed.");
    }
  };

  const pick = async (membership: MembershipChoiceView) => {
    if (loginToken) await enter(loginToken, membership);
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
