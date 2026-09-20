import { useMemo, useState } from "react";
import { errorMessage } from "../../app/errorMessage";
import { forgetSession } from "../../app/forgetSession";
import { useApiKeys, useCreateApiKey, useLogout, useMe, useRevokeApiKey, useUsers } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { apiKeyRows, canManageKeys, memberRows, signedInAs } from "./settingsModel";
import { signOut } from "./signOut";

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

  const members = useMemo(() => memberRows(users.data ?? []), [users.data]);
  const keys = useMemo(() => apiKeyRows(apiKeys.data ?? [], new Date()), [apiKeys.data]);

  // A write that fails is said, not swallowed: the notice names the refusal
  // and its request id, and the key list refetches on its own.
  const createApiKey = async () => {
    if (!newKeyName.trim()) return;
    try {
      const issued = await createKey.mutateAsync({ name: newKeyName.trim(), role: "member" });
      setIssuedKey(issued.key);
      setNewKeyName("");
    } catch (caught) {
      notify(errorMessage(caught, "The key was not created."));
    }
  };

  const revokeApiKey = (id: string) =>
    revokeKey.mutate(id, { onError: (caught) => notify(errorMessage(caught, "The key was not revoked.")) });

  // The server session is revoked, then the token and the cache go; the
  // realtime channel closes with the token. A sign-out finishes here even
  // when the server cannot be reached.
  const leave = () => void signOut({ revoke: () => logout.mutateAsync(), forget: forgetSession, report: notify });

  return {
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
    signOut: leave,
    signingOut: logout.isPending,
  };
}
