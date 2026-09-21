import { Button, Card, LinkButton, Muted, Page, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { useSignInVm } from "./useSignInVm";

export function SignInPage() {
  const vm = useSignInVm();
  return (
    <Page title="Sign in to Tadas">
      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void vm.submit();
          }}
          style={{ display: "grid", gap: 16 }}
        >
          <TextField label="Email" type="email" value={vm.email} onChange={vm.setEmail} autoComplete="username" />
          <TextField
            label="Password"
            type="password"
            value={vm.password}
            onChange={vm.setPassword}
            autoComplete="current-password"
          />
          {vm.error ? <Muted>{vm.error}</Muted> : null}
          <div style={{ display: "flex", alignItems: "center", gap: tokens.space.md }}>
            <Button type="submit" disabled={vm.busy}>
              Sign in
            </Button>
            <Muted>
              New here? <LinkButton onClick={vm.goToSignUp}>Create an account</LinkButton>
            </Muted>
          </div>
        </form>
      </Card>
      {vm.choice.kind === "several" ? (
        <Card title="Choose an organization">
          <div style={{ display: "grid", gap: 8 }}>
            {vm.choice.memberships.map((membership) => (
              <Button key={membership.org.id} tone="plain" onClick={() => void vm.pick(membership)}>
                {membership.org.name} <Muted>({membership.role})</Muted>
              </Button>
            ))}
          </div>
        </Card>
      ) : null}
    </Page>
  );
}
