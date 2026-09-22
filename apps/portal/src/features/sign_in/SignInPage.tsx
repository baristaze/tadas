import { Button, Card, ErrorText, LinkButton, Muted, Page, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { useSignInVm } from "./useSignInVm";

export function SignInPage() {
  const vm = useSignInVm();
  return (
    <Page title="Sign in to Tadas" narrow>
      {vm.choice.kind === "several" ? (
        <Card title="Choose an organization">
          <div style={{ display: "grid", gap: tokens.space.sm }}>
            {vm.choice.memberships.map((membership) => (
              <Button key={membership.org.id} tone="plain" wide onClick={() => void vm.pick(membership)}>
                <span style={{ display: "flex", justifyContent: "space-between", gap: tokens.space.md }}>
                  <span>{membership.org.name}</span>
                  <Muted>{membership.role}</Muted>
                </span>
              </Button>
            ))}
          </div>
        </Card>
      ) : (
        <Card>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void vm.submit();
            }}
            style={{ display: "grid", gap: tokens.space.md }}
          >
            <TextField label="Email" type="email" value={vm.email} onChange={vm.setEmail} autoComplete="username" />
            <TextField
              label="Password"
              type="password"
              value={vm.password}
              onChange={vm.setPassword}
              autoComplete="current-password"
            />
            {vm.error ? <ErrorText>{vm.error}</ErrorText> : null}
            <Button type="submit" wide disabled={vm.busy}>
              {vm.busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </Card>
      )}
      <Muted style={{ textAlign: "center", fontSize: tokens.font.size.sm }}>
        New here? <LinkButton onClick={vm.goToSignUp}>Create an account</LinkButton>
      </Muted>
    </Page>
  );
}
