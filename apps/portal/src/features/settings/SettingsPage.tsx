import { Banner, Button, Card, LinkButton, Muted, Page, Table, TextField } from "../../design/kit";
import { AppNav } from "../../app/AppNav";
import { tokens } from "../../design/tokens";
import { StorageCard } from "./StorageCard";
import { useSettingsVm, type SettingsVm } from "./useSettingsVm";

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
      <SlackCard slack={vm.slack} />
    </Page>
  );
}

function SlackCard({ slack }: { slack: SettingsVm["slack"] }) {
  const { summary, code } = slack;
  return (
    <Card title="Slack">
      {slack.loading ? (
        <Muted>Loading</Muted>
      ) : slack.error ? (
        <Banner>{slack.error.message}</Banner>
      ) : (
        <div style={{ display: "grid", gap: tokens.space.md }}>
          <div data-slack-state={summary.state}>{summary.line}</div>
          {summary.fix ? <Banner>{summary.fix}</Banner> : null}
          {code ? (
            <Banner>
              In the Slack channel, type <code>{code.invite}</code>, then <code>{code.command}</code>. The code
              works once and expires at {code.expiresAt}.{" "}
              <LinkButton onClick={slack.dismissCode}>dismiss</LinkButton>
            </Banner>
          ) : null}
          {slack.canManage ? (
            <div style={{ display: "flex", gap: tokens.space.sm }}>
              <Button onClick={() => void slack.connect()} disabled={slack.connecting}>
                {summary.connectLabel}
              </Button>
              {slack.connected ? (
                <Button tone="danger" onClick={() => void slack.disconnect()} disabled={slack.disconnecting}>
                  Disconnect
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}
