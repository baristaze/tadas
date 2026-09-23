import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type {
  AddApiKeyRequest,
  ApiKeyPageView,
  ApiKeyView,
  CreateTeamOrgRequest,
  ExchangeSessionRequest,
  IssuedApiKeyView,
  IssuedLoginView,
  IssuedSessionView,
  LoginRequest,
  MembershipChoicePageView,
  MembershipChoiceView,
  MeView,
  SessionView,
  SignUpRequest,
  UserPageView,
  UserView,
} from "../api";
import { api } from "../app/api";
import { keys } from "./keys";

/** Both lists are paged by the server's cursor; these are page sizes, not
 * ceilings, so nothing is hidden past the end of the first page. The member
 * list is read whole (below), so it asks for the largest page the server
 * gives; the key list is read a page at a time on the screen that shows it. */
const USERS_PAGE_SIZE = 200;
export const API_KEYS_PAGE_SIZE = 50;
/** A person belongs to at most a hundred orgs; the chip reads them whole. */
const MY_MEMBERSHIPS_PAGE_SIZE = 200;

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: ({ signal }) => api.get<MeView>("/v1/me", { signal }) });
}

/** Every member of the org, page after page. The list is not a screen of its
 * own: it names the people on tasks and fills the assignee picker, and a
 * member missing from it reads as "someone" and cannot be assigned, so this
 * follows the cursor to the end rather than stopping at one page. The pages
 * loaded so far are returned as they arrive. */
export function useUsers() {
  const query = useInfiniteQuery({
    queryKey: keys.users.list(USERS_PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last: UserPageView) => last.next_cursor,
    queryFn: ({ pageParam, signal }) => {
      const cursor = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return api.get<UserPageView>(`/v1/users?limit=${USERS_PAGE_SIZE}${cursor}`, { signal });
    },
  });
  const { hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = query;
  // A page that failed is not asked for again on its own: retries are the
  // client's, and re-firing here on every render would be a loop against a
  // server that just refused. The pages in hand are what the app shows, and
  // the next invalidation starts the walk over.
  const walking = hasNextPage && !isFetchNextPageError;
  useEffect(() => {
    if (walking && !isFetchingNextPage) void fetchNextPage();
  }, [walking, isFetchingNextPage, fetchNextPage]);
  return {
    ...query,
    data: query.data?.pages.flatMap((page) => page.items) as UserView[] | undefined,
    /** Pending until the whole list is in hand: a caller that maps ids to
     * names would otherwise render "someone" for a member still on the way. */
    isPending: query.isPending || walking,
  };
}

/** Only a member who may manage keys asks for them: `GET /v1/api-keys`
 * refuses anyone else, and a refusal nobody can act on is not an error to
 * show. Disabled, the query stays pending and never fetches, so a caller
 * reads `enabled` and not `isPending` to know whether to wait. The list is
 * paged on demand: the screen shows the first page and asks for the next. */
export function useApiKeys(enabled = true) {
  const query = useInfiniteQuery({
    queryKey: keys.apiKeys.list(API_KEYS_PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last: ApiKeyPageView) => last.next_cursor,
    queryFn: ({ pageParam, signal }) => {
      const cursor = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return api.get<ApiKeyPageView>(`/v1/api-keys?limit=${API_KEYS_PAGE_SIZE}${cursor}`, {
        signal,
      });
    },
    enabled,
  });
  return {
    ...query,
    data: query.data?.pages.flatMap((page) => page.items) as ApiKeyView[] | undefined,
  };
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

/** The orgs the signed-in person belongs to, page after page, read with the
 * session this tab holds. The chip needs the whole list to offer a switch. */
export function useMyMemberships() {
  const query = useInfiniteQuery({
    queryKey: keys.myMemberships.list(MY_MEMBERSHIPS_PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last: MembershipChoicePageView) => last.next_cursor,
    queryFn: ({ pageParam, signal }) => {
      const cursor = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return api.get<MembershipChoicePageView>(
        `/v1/auth/memberships?limit=${MY_MEMBERSHIPS_PAGE_SIZE}${cursor}`,
        { signal },
      );
    },
  });
  const { hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = query;
  const walking = hasNextPage && !isFetchNextPageError;
  useEffect(() => {
    if (walking && !isFetchingNextPage) void fetchNextPage();
  }, [walking, isFetchingNextPage, fetchNextPage]);
  return {
    ...query,
    data: query.data?.pages.flatMap((page) => page.items) as MembershipChoiceView[] | undefined,
    isPending: query.isPending || walking,
  };
}

/** A new person, who comes with their personal org. Answered as a sign-in
 * is, so the flow goes on to the exchange. Sent once, with no bearer and no
 * idempotency key: a retry would meet the email the first attempt took. */
export function useSignUp() {
  return useMutation({
    mutationFn: (body: SignUpRequest) =>
      api.post<IssuedLoginView>("/v1/auth/signup", body, { token: null }),
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

/** The switch: the exchange presented with the session this tab holds. The
 * server ends that session in the same write and answers with the new one. */
export function useSwitchOrg() {
  return useMutation({
    mutationFn: (orgId: string) => api.post<IssuedSessionView>("/v1/auth/sessions", { org_id: orgId }),
  });
}

/** A team org the signed-in person makes and owns, from the tenant they are
 * in. A creating POST, so it carries an idempotency key and a retry makes
 * one org. The answer is the person's place in it, which the switch takes;
 * the list of places is read again, since no push names it. */
export function useCreateOrg() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateTeamOrgRequest) =>
      api.post<MembershipChoiceView>("/v1/orgs", body, { idempotencyKey: crypto.randomUUID() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.myMemberships.all }),
  });
}
