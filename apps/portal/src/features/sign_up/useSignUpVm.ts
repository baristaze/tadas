import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { adoptSession } from "../../app/adoptSession";
import { useExchangeSession, useSignUp } from "../../queries/tenancy";
import { chooseOrg } from "../sign_in/signInModel";
import { checkSignUp, signUpRefusal } from "./signUpModel";

export function useSignUpVm() {
  const navigate = useNavigate();
  const signUp = useSignUp();
  const exchange = useExchangeSession();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [offerSignIn, setOfferSignIn] = useState(false);

  const submit = async () => {
    setError(null);
    setOfferSignIn(false);
    const form = { email, displayName, password };
    const check = checkSignUp(form);
    if (!check.ok) {
      setError(check.message);
      return;
    }
    try {
      const issued = await signUp.mutateAsync({ email, password, display_name: displayName.trim() });
      // The answer is a sign-in's: the one membership, the person's personal
      // org, then the same exchange.
      const choice = chooseOrg(issued.memberships);
      if (choice.kind !== "single") {
        setError("The account was created; sign in to continue.");
        return;
      }
      const session = await exchange.mutateAsync({
        loginToken: issued.token,
        body: { org_id: choice.membership.org.id },
      });
      adoptSession(session);
      navigate("/", { replace: true });
    } catch (caught) {
      const refusal = signUpRefusal(caught, "Sign-up failed.");
      setError(refusal.message);
      setOfferSignIn(refusal.signIn);
    }
  };

  return {
    email,
    displayName,
    password,
    error,
    offerSignIn,
    busy: signUp.isPending || exchange.isPending,
    setEmail,
    setDisplayName,
    setPassword,
    submit,
    goToSignIn: () => navigate("/sign-in"),
  };
}
