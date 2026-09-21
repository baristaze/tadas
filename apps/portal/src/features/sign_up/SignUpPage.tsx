import { Button, Card, LinkButton, Muted, Page, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { useSignUpVm } from "./useSignUpVm";

export function SignUpPage() {
  const vm = useSignUpVm();
  return (
    <Page title="Create your Tadas account">
      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void vm.submit();
          }}
          style={{ display: "grid", gap: 16 }}
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
          <TextField label="Organization" value={vm.orgName} onChange={vm.setOrgName} autoComplete="organization" />
          <TextField label="Short name (in links and the command line)" value={vm.orgSlug} onChange={vm.setOrgSlug} />
          {vm.error ? (
            <Muted>
              {vm.error} {vm.offerSignIn ? <LinkButton onClick={vm.goToSignIn}>Sign in</LinkButton> : null}
            </Muted>
          ) : null}
          <div style={{ display: "flex", alignItems: "center", gap: tokens.space.md }}>
            <Button type="submit" disabled={vm.busy}>
              Create account
            </Button>
            <Muted>
              Have an account? <LinkButton onClick={vm.goToSignIn}>Sign in</LinkButton>
            </Muted>
          </div>
        </form>
      </Card>
    </Page>
  );
}
