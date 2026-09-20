import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AddApiKeyRequest,
  ApiKeyView,
  ExchangeSessionRequest,
  IssuedApiKeyView,
  IssuedLoginView,
  IssuedSessionView,
  LoginRequest,
  MeView,
  SessionView,
  UserView,
} from "../api";
import { api } from "../app/api";
import { keys } from "./keys";

const LIMIT = 100;

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: () => api.get<MeView>("/v1/me") });
}

export function useUsers() {
  return useQuery({
    queryKey: keys.users.list(LIMIT),
    queryFn: () => api.get<UserView[]>(`/v1/users?limit=${LIMIT}`),
  });
}

/** Only a member who may manage keys asks for them: `GET /v1/api-keys`
 * refuses anyone else, and a refusal nobody can act on is not an error to
 * show. Disabled, the query stays pending and never fetches, so a caller
 * reads `enabled` and not `isPending` to know whether to wait. */
export function useApiKeys(enabled = true) {
  return useQuery({
    queryKey: keys.apiKeys.list(LIMIT),
    queryFn: () => api.get<ApiKeyView[]>(`/v1/api-keys?limit=${LIMIT}`),
    enabled,
  });
}

export function useCreateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AddApiKeyRequest) =>
      api.post<IssuedApiKeyView>("/v1/api-keys", body, { idempotencyKey: crypto.randomUUID() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.apiKeys.all }),
  });
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (apiKeyId: string) => api.del<ApiKeyView>(`/v1/api-keys/${apiKeyId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.apiKeys.all }),
  });
}

export function useLogin() {
  return useMutation({
    mutationFn: (body: LoginRequest) =>
      api.post<IssuedLoginView>("/v1/auth/login", body, { token: null }),
  });
}

/** Revokes the session the token names; the server answers with the session, revoked. */
export function useLogout() {
  return useMutation({ mutationFn: () => api.post<SessionView>("/v1/auth/logout") });
}

export function useExchangeSession() {
  return useMutation({
    mutationFn: ({ loginToken, body }: { loginToken: string; body: ExchangeSessionRequest }) =>
      api.post<IssuedSessionView>("/v1/auth/sessions", body, { token: loginToken }),
  });
}
