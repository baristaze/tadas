import { Button, Card, ErrorText, LinkButton, Muted, Page, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { useSignUpVm } from "./useSignUpVm";

export function SignUpPage() {
  const vm = useSignUpVm();
  return (
    <Page title="Create your Tadas account" narrow>
      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void vm.submit();
          }}
          style={{ display: "grid", gap: tokens.space.md }}
        >
          <TextField label="Email" type="email" value={vm.email} onChange={vm.setEmail} autoComplete="username" />
          <TextField label="Your name" value={vm.displayName} onChange={vm.setDisplayName} autoComplete="name" />
          <TextField
            label="Password (at least 8 characters)"
            type="password"
            value={vm.password}
            onChange={vm.setPassword}
            autoComplete="new-password"
          />
          <Muted style={{ fontSize: tokens.font.size.sm }}>
            You start in a personal organization of your own. Create one for a team any time from the
            organization menu.
          </Muted>
          {vm.error ? (
            <ErrorText>
              {vm.error} {vm.offerSignIn ? <LinkButton onClick={vm.goToSignIn}>Sign in</LinkButton> : null}
            </ErrorText>
          ) : null}
          <Button type="submit" wide disabled={vm.busy}>
            {vm.busy ? "Creating your account…" : "Create account"}
          </Button>
        </form>
      </Card>
      <Muted style={{ textAlign: "center", fontSize: tokens.font.size.sm }}>
        Have an account? <LinkButton onClick={vm.goToSignIn}>Sign in</LinkButton>
      </Muted>
    </Page>
  );
}
