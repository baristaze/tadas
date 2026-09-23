import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { IssuedSlackLinkCodeView, SlackStatusView } from "../api";
import { api } from "../app/api";
import { keys } from "./keys";

/** Whether the org has a Slack channel connected, and which. Any member reads it. */
export function useSlackStatus() {
  return useQuery({
    queryKey: keys.slack.connection,
    queryFn: ({ signal }) => api.get<SlackStatusView>("/v1/slack/connection", { signal }),
  });
}

/** A one-time code to type in the channel. Sent once, with no idempotency
 * key: a code the first attempt issued and nobody saw simply expires. */
export function useIssueSlackLinkCode() {
  return useMutation({
    mutationFn: () => api.post<IssuedSlackLinkCodeView>("/v1/slack/link-codes"),
  });
}

export function useDisconnectSlack() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.del<SlackStatusView>("/v1/slack/connection"),
    onSuccess: (status) => queryClient.setQueryData(keys.slack.connection, status),
  });
}
