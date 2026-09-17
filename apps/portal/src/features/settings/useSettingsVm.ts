import { useMemo, useState } from "react";
import { useApiKeys, useCreateApiKey, useMe, useRevokeApiKey, useUsers } from "../../queries/tenancy";
import { useSessionStore } from "../../store/session";
import { apiKeyRows, canManageKeys, memberRows, signedInAs } from "./settingsModel";

export function useSettingsVm() {
  const me = useMe();
  const users = useUsers();
  const apiKeys = useApiKeys();
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey();
  const clearSession = useSessionStore((s) => s.clear);
  const [newKeyName, setNewKeyName] = useState("");
  const [issuedKey, setIssuedKey] = useState<string | null>(null);

  const members = useMemo(() => memberRows(users.data ?? []), [users.data]);
  const keys = useMemo(() => apiKeyRows(apiKeys.data ?? [], new Date()), [apiKeys.data]);

  const createApiKey = async () => {
    if (!newKeyName.trim()) return;
    const issued = await createKey.mutateAsync({ name: newKeyName.trim(), role: "member" });
    setIssuedKey(issued.key);
    setNewKeyName("");
  };

  return {
    signedInAs: signedInAs(me.data),
    loading: me.isPending || users.isPending || apiKeys.isPending,
    error: me.error ?? users.error ?? apiKeys.error,
    members,
    keys,
    canManageKeys: canManageKeys(me.data),
    newKeyName,
    setNewKeyName,
    issuedKey,
    dismissIssuedKey: () => setIssuedKey(null),
    createApiKey,
    creating: createKey.isPending,
    revokeApiKey: (id: string) => revokeKey.mutate(id),
    signOut: clearSession,
  };
}
