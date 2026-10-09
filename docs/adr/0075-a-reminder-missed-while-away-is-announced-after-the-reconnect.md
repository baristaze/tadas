# ADR 0075: A reminder missed while away is announced after the reconnect

**Status**: accepted (2026-09-26)

## Context

A reminder is the one push a person is told about, not only refreshed
by. A live `tasks.task.reminded` push shows a notice with the task's
title, and the task shows its reminded badge.

A portal that was away misses the push: the network dropped, the API
restarted, or the tab was hidden long enough to pause its socket
([ADR 0064](0064-a-hidden-tab-pauses-its-socket.md)). When it comes
back, the replay reads the stream after its cursor. The guideline makes
that the durability mechanism (Realtime at the Edge): "Replay from
storage is the durability mechanism. The socket is a hint that
something changed."

The scaffold's channel has notices: records a person is told about, not
only refreshed by. It hands each one over once, as its cursor passes it,
keeps them apart from a replay's collapse to one record per entity, and
hands over nothing once it stops
([ADR 0096](0096-a-notice-is-handed-over-once-as-the-cursor-passes-it.md)).

## Decision

**A reminder the portal missed is announced after the reconnect.**

**A reminder is a notice.** The provider's `isAnnounced` names
`tasks.task.reminded`, and its `announce` is the one place a reminder is
told, live or missed (`reminderNotices` in `reminder.ts`). The channel
hands a live push over at once, and what a replay or the first catch-up
read when it ends, in stream order, however it ends. `route` refreshes
the task and tells nothing, so no reminder is told twice. A switch of
org and a sign-out stop the channel, so a replay from the old session
announces nothing in the new one.

**Three by name, then a count.** What the channel hands over at once is
announced each as "Reminder: <title>", with one read of the task for its
title, one after another, up to three. Past three, one notice counts
them: "You missed 5 reminders while you were away." It reads nothing,
and the badges show which tasks. A task reminded twice in one replay
counts once. A live push hands over one.

**The window is the replay's own.** Nothing is read to find missed
reminders. What the replay reads after the cursor is what is announced.
A stream trimmed past the cursor is a resync that reads no record
([ADR 0040](0040-the-event-stream-has-a-floor.md)), so it announces
nothing.

## Consequences

A person who comes back to the portal learns what came due while they
were away, as a paused tab does
([ADR 0064](0064-a-hidden-tab-pauses-its-socket.md)).

A replay with more than three reminders costs no extra read. One with
three or fewer costs a read of each task, the read a live reminder makes
for its title, one after another.

A degraded channel polls by replaying every thirty seconds, so a
reminder that fires while it is degraded is announced by the next poll.

A reload inside the first catch-up's window (fifteen seconds, and the
page's own load) announces a reminder that fired in it again. A notice
twice beats a notice never.
