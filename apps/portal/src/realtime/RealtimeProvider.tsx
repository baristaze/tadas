// One provider owns the socket for the whole app; the loop itself lives in
// channel.ts, without React, and this component gives it the query cache, the
// transport client, the connection store, the page's visibility, and the hint
// readers, announces reminders, and shows the degraded banner. A paused socket
// shows none: it is not a failure.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import type { IssuedTicketView } from "@tadas/client";
import { api } from "../app/api";
import { forgetSessionIfHeld } from "../app/forgetSession";
import { Banner } from "../design/kit";
import { EVENTS_PAGE, fetchEventsAfter } from "../queries/events";
import { taskHintEffects } from "../queries/taskCache";
import { fetchTask } from "../queries/tasks";
import { fetchUser } from "../queries/tenancy";
import { userHintEffects } from "../queries/userCache";
import { useConnectionStore } from "../store/connection";
import { notify } from "../store/notices";
import { useSessionStore } from "../store/session";
import { openChannel } from "./channel";
import { createHints } from "./hints";
import { watchPage } from "./pageVisibility";
import { announceMissedReminders, announceReminder } from "./reminder";
import { reminderOf, replayKey, routeEnvelope, type HintReaders } from "./router";

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const token = useSessionStore((s) => s.token);
  const status = useConnectionStore((s) => s.status);

  useEffect(() => {
    if (!token) return;
    // A push about a user reads that one member, and one about a task that
    // one task; one reader each per session, so a switch starts with none of
    // the old tenant's answers.
    const readers: HintReaders = {
      user: createHints(userHintEffects(queryClient, fetchUser)),
      task: createHints(taskHintEffects(queryClient, fetchTask)),
    };
    const channel = openChannel({
      requestTicket: async () => (await api.post<IssuedTicketView>("/v1/realtime/tickets")).ticket,
      openSocket: (ticket) =>
        new WebSocket(api.websocketUrl(`/v1/realtime?ticket=${encodeURIComponent(ticket)}`)),
      fetchEventsAfter,
      route: (envelope) => {
        routeEnvelope(queryClient, envelope, readers);
        const reminded = reminderOf(envelope);
        if (reminded) void announceReminder(reminded, { readTask: fetchTask, notify });
      },
      routeReplayed: (envelope) => void routeEnvelope(queryClient, envelope, readers),
      replayKey: (envelope) => replayKey(envelope, readers),
      // A reminder read back from the stream (the replay after a reconnect,
      // the first catch-up) is kept through the replay's collapse, and
      // announced once the read-back ends.
      isAnnounced: (envelope) => reminderOf(envelope) !== null,
      announce: (envelopes) => {
        const reminded = envelopes.map(reminderOf).filter((id): id is string => id !== null);
        void announceMissedReminders(reminded, { readTask: fetchTask, notify });
      },
      refreshAll: () => queryClient.invalidateQueries(),
      connection: useConnectionStore,
      pageSize: EVENTS_PAGE,
      // A socket opened under a session a switch has ended closes with 4401
      // too; only a close for the session the tab still holds signs it out.
      onUnauthenticated: () => forgetSessionIfHeld(token),
    });
    // A hidden tab's socket pauses, and any sign of the person's return
    // (shown, restored, focused, back online) resumes it. A session that
    // expired meanwhile is refused its ticket with a 401, which signs out.
    const unwatch = watchPage({ document, window }, channel);
    return () => {
      unwatch();
      channel.stop();
      for (const reader of Object.values(readers)) reader.stop();
    };
  }, [token, queryClient]);

  return (
    <>
      {status === "degraded" ? (
        <Banner>Live updates are unavailable; refreshing every 30 seconds until they return.</Banner>
      ) : null}
      {children}
    </>
  );
}
