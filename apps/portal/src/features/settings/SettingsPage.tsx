import { Banner, Button, Card, LinkButton, Muted, Page, Table, TextField } from "../../design/kit";
import { AppNav } from "../../app/AppNav";
import { tokens } from "../../design/tokens";
import { StorageCard } from "./StorageCard";
import { useSettingsVm } from "./useSettingsVm";

export function SettingsPage() {
  const vm = useSettingsVm();
  return (
    <Page title="Settings" nav={<AppNav />}>
      <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
        {vm.signedInAs ? <Muted>{vm.signedInAs}</Muted> : null}
        <Button tone="plain" onClick={vm.signOut} disabled={vm.signingOut}>
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
      <StorageCard />
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
                <Button tone="danger" onClick={() => void vm.revokeApiKey(k.id)}>
                  Revoke
                </Button>
              ) : (
                ""
              ),
            ])}
          />
          {vm.hasMoreKeys ? (
            <div style={{ paddingTop: tokens.space.md }}>
              {vm.loadingMoreKeys ? (
                <Muted>Loading</Muted>
              ) : (
                <LinkButton onClick={vm.showMoreKeys}>Show more</LinkButton>
              )}
            </div>
          ) : null}
        </Card>
      ) : null}
    </Page>
  );
}
