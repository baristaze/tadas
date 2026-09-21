import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { adoptSession } from "../../app/adoptSession";
import { useExchangeSession, useSignUp } from "../../queries/tenancy";
import { chooseOrg } from "../sign_in/signInModel";
import { checkSignUp, signUpRefusal, slugAfterNameChange } from "./signUpModel";

export function useSignUpVm() {
  const navigate = useNavigate();
  const signUp = useSignUp();
  const exchange = useExchangeSession();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgNameValue] = useState("");
  const [orgSlug, setOrgSlugValue] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offerSignIn, setOfferSignIn] = useState(false);

  const setOrgName = (value: string) => {
    setOrgNameValue(value);
    setOrgSlugValue((slug) => slugAfterNameChange(value, slug, slugEdited));
  };
  const setOrgSlug = (value: string) => {
    setSlugEdited(true);
    setOrgSlugValue(value);
  };

  const submit = async () => {
    setError(null);
    setOfferSignIn(false);
    const form = { email, displayName, password, orgName, orgSlug };
    const check = checkSignUp(form);
    if (!check.ok) {
      setError(check.message);
      return;
    }
    try {
      const issued = await signUp.mutateAsync({
        email,
        password,
        display_name: displayName.trim(),
        org_name: orgName.trim(),
        org_slug: orgSlug,
      });
      // The answer is a sign-in's: the one membership, then the same exchange.
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
    orgName,
    orgSlug,
    error,
    offerSignIn,
    busy: signUp.isPending || exchange.isPending,
    setEmail,
    setDisplayName,
    setPassword,
    setOrgName,
    setOrgSlug,
    submit,
    goToSignIn: () => navigate("/sign-in"),
  };
}
