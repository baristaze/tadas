import { useMemo, useState } from "react";
import { useApiKeys, useCreateApiKey, useMe, useRevokeApiKey, useUsers } from "../../queries/tenancy";
import { useConnectionStore } from "../../store/connection";
import { useSessionStore } from "../../store/session";
import { apiKeyRows, canManageKeys, headline, memberRows } from "./homeModel";

export function useHomeVm() {
  const me = useMe();
  const users = useUsers();
  const apiKeys = useApiKeys();
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey();
  const clearSession = useSessionStore((s) => s.clear);
  const connection = useConnectionStore((s) => s.status);
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
    title: headline(me.data),
    me: me.data,
    loading: me.isPending || users.isPending || apiKeys.isPending,
    error: me.error ?? users.error ?? apiKeys.error,
    members,
    keys,
    canManageKeys: canManageKeys(me.data),
    connection,
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
