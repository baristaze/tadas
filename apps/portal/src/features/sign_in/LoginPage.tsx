import { useNavigate } from "react-router-dom";
import { Button, Card, ErrorText, LinkButton, Muted, Page } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { useLoginVm } from "./useLoginVm";

export function LoginPage() {
  const vm = useLoginVm();
  const navigate = useNavigate();
  return (
    <Page title="Sign in to Tadas" narrow>
      <Card>
        <div style={{ display: "grid", gap: tokens.space.md }}>
          {vm.error ? (
            <>
              <ErrorText>{vm.error}</ErrorText>
              <Button wide onClick={vm.retry}>
                Try again
              </Button>
            </>
          ) : vm.wait ? (
            <>
              {vm.signedOut ? <Muted>You are signed out.</Muted> : null}
              <Button wide onClick={vm.retry}>
                Sign in
              </Button>
            </>
          ) : (
            <Muted>Taking you to sign in…</Muted>
          )}
        </div>
      </Card>
      {vm.devSignIn ? (
        <Muted style={{ textAlign: "center", fontSize: tokens.font.size.sm }}>
          On the local stack: <LinkButton onClick={() => navigate("/login/dev")}>the local sign-in</LinkButton>
        </Muted>
      ) : null}
    </Page>
  );
}
