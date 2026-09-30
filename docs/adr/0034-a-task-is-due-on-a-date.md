# ADR 0034: A task is due on a date, reminded at nine in its person's morning

**Status**: accepted (2026-09-23)

## Context

People think of a to-do as due on a day, not at a minute, and asking for
a time makes the quick add a form of two fields. A task carries
`due_on`, a date and never a time, and the quick add is one text box: a
title and Enter. The date is set by editing the task.

A date has no hour, and the reminder needs one. The worker fires one
reminder per due date, in one conditional write. So one question
follows: at what moment does a date's reminder go out?

## Decision

**Nine in the morning, in the time zone of the person the task is for.**
That person is the assignee, or the creator when the task is unassigned
(`tasks.rules.reminder_person`). Nine is early enough to plan the day
around, and late enough not to arrive in the night. The rule is one pure
function, `tasks.rules.reminder_time(due_on, zone)`. A zone that is
unknown, or missing, means UTC. It is the person's nine, never nine UTC
for everyone: that reminds a person in Tokyo at six in the evening and
one in Honolulu at eleven at night, the day before.

**The time zone is the person's, recorded from the portal.** An
identity carries `time_zone`, an IANA name (`Europe/Istanbul`). The
portal reads the browser's own
(`Intl.DateTimeFormat().resolvedOptions().timeZone`) once a person is
signed in, and sends it with `PATCH /v1/me/identity` when it differs
from the stored one. So a person who travels has their zone moved the
next time they open the portal. The zone lives on the identity, not the
user, because a person has one morning in every org they are in.
`tenancy.rules.check_time_zone` refuses anything that is not a name the
process knows, an offset like `+03:00` among them: an offset has no
daylight saving, and the reminder would drift by an hour for half the
year.

**The zone is read when the reminder runs, not when the date is set.**
The write that sets a date lands the work row, available from
`earliest_reminder_time`: nine in the morning at UTC+14, the first
morning of that date anywhere. When the item runs, the handler asks
`get_due_reminder` for the task's date and the moment in its person's
zone, and parks until then (`WorkParked`, which spends no attempt). A
task handed to someone in another zone, or a person whose zone moved,
is still met on their morning. A reassignment lands a second row, so a
reminder already parked for the old person's later morning does not
hold back the new person's earlier one. Two rows for one date are
harmless: `fire_reminder` is one write conditioned on the task being
open, living, still due on the date read, and not yet reminded, so one
of them lands and the other writes nothing.

**The wire carries a date.** `TaskView`, `AddTaskRequest`, and
`UpdateTaskRequest` carry `due_on`, and an explicit `null` clears it.
The CLI takes `--due 2026-10-01` and `--no-due`, and refuses a time.

## Consequences

Every reminder item is claimed at least once before its person's
morning and parked. That is one extra claim per reminder, which a
reminder a week out already pays in the queue's wait.

A person who never opens the portal has no zone, and is reminded at
nine UTC. The CLI does not send one.
