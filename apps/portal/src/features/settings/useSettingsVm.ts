import { useMemo, useState } from "react";
import { errorMessage } from "../../app/errorMessage";
import { forgetSession } from "../../app/forgetSession";
import { useDisconnectSlack, useIssueSlackLinkCode, useSlackStatus } from "../../queries/slack";
import { useApiKeys, useCreateApiKey, useLogout, useMe, useRevokeApiKey, useUsers } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { noteSignedOut } from "../../store/signInState";
import { apiKeyRows, canManageKeys, memberRows, signedInAs } from "./settingsModel";
import { signOut } from "./signOut";
import {
  canManageSlack,
  clockOf,
  codeStillPending,
  INVITE_COMMAND,
  issuedCode,
  linkCommand,
  slackSummary,
  type IssuedCode,
} from "./slackModel";

export function useSettingsVm() {
  const me = useMe();
  const users = useUsers();
  const mayManageKeys = canManageKeys(me.data);
  const apiKeys = useApiKeys(mayManageKeys);
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey();
  const logout = useLogout();
  const notify = useNoticesStore((s) => s.notify);
  const [newKeyName, setNewKeyName] = useState("");
  const [issuedKey, setIssuedKey] = useState<string | null>(null);
  const slack = useSlackStatus();
  const issueCode = useIssueSlackLinkCode();
  const disconnect = useDisconnectSlack();
  const mayManageSlack = canManageSlack(me.data);
  const [slackCode, setSlackCode] = useState<IssuedCode | null>(null);

  const members = useMemo(() => memberRows(users.data ?? []), [users.data]);
  const keys = useMemo(() => apiKeyRows(apiKeys.data ?? [], new Date()), [apiKeys.data]);

  // A write that fails is said, not swallowed: the notice names the refusal
  // and its request id, and the key list refetches on its own.
  const createApiKey = async () => {
    if (!newKeyName.trim()) return;
    try {
      const issued = await createKey.mutateAsync({ name: newKeyName.trim(), role: "member" });
      // A retried create the server answers from its record carries no
      // secret: the first answer, the only one that had it, was lost. The key
      // exists and nobody can use it, which is said, not shown as success.
      if (issued.key === null) {
        setIssuedKey(null);
        notify(`The key "${issued.api_key.name}" was created, but its secret was lost on the way back; revoke it and create another.`);
      } else {
        setIssuedKey(issued.key);
      }
      setNewKeyName("");
    } catch (caught) {
      notify(errorMessage(caught, "The key was not created."));
    }
  };

  // Awaited, not handed to `mutate` as per-call callbacks: one hook holds one
  // mutation observer, and a second revoke started before the first answers
  // drops the first call's callbacks, so its refusal would go unsaid.
  const revokeApiKey = async (id: string) => {
    try {
      await revokeKey.mutateAsync(id);
    } catch (caught) {
      notify(errorMessage(caught, "The key was not revoked."));
    }
  };

  // A code is shown until it is used (the connection's push refreshes the
  // status, and the status moves on from where it stood), or dismissed.
  const connectSlack = async () => {
    try {
      const issued = await issueCode.mutateAsync();
      const code = issuedCode(issued, slack.data);
      if (code === null) notify("A code was issued, but it was lost on the way back; ask for another.");
      setSlackCode(code);
    } catch (caught) {
      notify(errorMessage(caught, "No code was issued."));
    }
  };

  const disconnectSlack = async () => {
    try {
      await disconnect.mutateAsync();
      setSlackCode(null);
    } catch (caught) {
      notify(errorMessage(caught, "Slack was not disconnected."));
    }
  };

  const shownCode = slackCode && codeStillPending(slackCode, slack.data) ? slackCode : null;

  // The server session is revoked, then the token and the cache go; the
  // realtime channel closes with the token. A sign-out finishes here even
  // when the server cannot be reached.
  // `/login` then waits for the person to ask, rather than starting a sign-in
  // the provider's own session would answer at once.
  const forget = () => {
    noteSignedOut();
    forgetSession();
  };
  const leave = () => void signOut({ revoke: () => logout.mutateAsync(), forget, report: notify });

  return {
    me: me.data,
    signedInAs: signedInAs(me.data),
    loading: me.isPending || users.isPending || (mayManageKeys && apiKeys.isPending),
    error: me.error ?? users.error ?? (mayManageKeys ? apiKeys.error : null),
    members,
    keys,
    canManageKeys: mayManageKeys,
    // The key list is paged: the screen shows a page and asks for the next,
    // so a key past the first page is still there to revoke.
    hasMoreKeys: apiKeys.hasNextPage,
    loadingMoreKeys: apiKeys.isFetchingNextPage,
    showMoreKeys: () => void apiKeys.fetchNextPage(),
    newKeyName,
    setNewKeyName,
    issuedKey,
    dismissIssuedKey: () => setIssuedKey(null),
    createApiKey,
    creating: createKey.isPending,
    revokeApiKey,
    slack: {
      loading: slack.isPending,
      error: slack.error,
      summary: slackSummary(slack.data),
      connected: Boolean(slack.data?.connection),
      canManage: mayManageSlack,
      code: shownCode && {
        invite: INVITE_COMMAND,
        command: linkCommand(shownCode.code),
        expiresAt: clockOf(shownCode.expiresAt),
      },
      dismissCode: () => setSlackCode(null),
      connect: connectSlack,
      connecting: issueCode.isPending,
      disconnect: disconnectSlack,
      disconnecting: disconnect.isPending,
    },
    signOut: leave,
    signingOut: logout.isPending,
  };
}

export type SettingsVm = ReturnType<typeof useSettingsVm>;
