import { Banner, Button, Card, Muted, Page, Table, TextField } from "../../design/kit";
import { useHomeVm } from "./useHomeVm";

export function HomePage() {
  const vm = useHomeVm();
  return (
    <Page title={vm.title}>
      <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
        {vm.me ? (
          <Muted>
            Signed in as {vm.me.user.display_name} ({vm.me.role}); live updates: {vm.connection}
          </Muted>
        ) : null}
        <Button tone="plain" onClick={vm.signOut}>
          Sign out
        </Button>
      </div>
      {vm.error ? <Banner>{vm.error.message}</Banner> : null}
      <Card title="Members">
        {vm.loading ? (
          <Muted>Loading</Muted>
        ) : (
          <Table headers={["Name", "Email", "Joined"]} rows={vm.members.map((m) => [m.name, m.email, m.joined])} />
        )}
      </Card>
      {vm.canManageKeys ? (
        <Card title="API keys">
          {vm.issuedKey ? (
            <Banner>
              Copy this key now; it is shown once: <code>{vm.issuedKey}</code>{" "}
              <Button tone="plain" onClick={vm.dismissIssuedKey}>
                Done
              </Button>
            </Banner>
          ) : null}
          <div style={{ display: "flex", gap: 8, alignItems: "end", margin: "16px 0" }}>
            <TextField label="New key name" value={vm.newKeyName} onChange={vm.setNewKeyName} />
            <Button onClick={() => void vm.createApiKey()} disabled={vm.creating}>
              Create key
            </Button>
          </div>
          <Table
            headers={["Name", "Role", "State", "Expires", ""]}
            rows={vm.keys.map((k) => [
              k.name,
              k.role,
              k.state,
              k.expires,
              k.state === "active" ? (
                <Button tone="danger" onClick={() => vm.revokeApiKey(k.id)}>
                  Revoke
                </Button>
              ) : (
                ""
              ),
            ])}
          />
        </Card>
      ) : null}
    </Page>
  );
}
