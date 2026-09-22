# Outbox rows

The note written beside every change, from which the event and the
push come. This is one of the six kinds of thing
[Tadas is made of](../../../../README.md).

## The nouns

- **Outbox row**: the org, the kind of change, the id of the record
  that changed, and the provenance of the write: the
  actor, the request, the request's trace context, and the app. It
  records when it was relayed, how many attempts the sweep has spent
  on it, when the next is due, its last error, and whether it failed
  for good.
- **Kind** is the row's destination. `<namespace>.<entity>.<action>`
  announces a change and becomes an event. `work.<kind>` asks for a
  job and becomes a work item.

## What can happen

- **Written with the change.** The rows that announce a write are
  handed over with the write itself, and both land in one commit.
  There is no second step anyone could forget.
- **Relayed at once.** The row is relayed in the request's own path.
  A change appends its event and publishes a push; a request for work
  enqueues the item under the row's id and wakes the workers. Either
  way the row is marked done.
- **Relayed by the sweep.** Whatever the request path left behind is
  claimed by the maintenance sweep, oldest first, one attempt at a
  time, with a delay that doubles per attempt. A row whose attempts
  are spent is failed for good, counted, and named by an event in the
  org's diary.
- **Purged.** Done and failed rows are erased after the retention,
  eight days by default.

## The rules

- **Same commit or nothing.** The row lands with the change it
  announces, or neither lands.
- **Ids, never values.** A row names the record that changed and
  carries no field of it, so the relay and the stream hold nothing a
  person's erasure has to find. A client that hears of a change reads
  the record.
- **Relaying twice is harmless.** The relay is idempotent on the row's
  id: the event is appended once and the work item is enqueued once.
- **A failed relay never fails the request.** It is logged and
  counted; the row is durable and the sweep relays it again.
- **A stuck row blocks nothing behind it.** Each attempt sets the next
  one later, so a row that will not relay waits on its own.
- **A young row is the request path's.** The sweep leaves rows younger
  than a grace period alone, so two relays do not race for one row.
- **The retention outlives the backup.** Done rows are kept longer
  than the database backups are, so a restore to an earlier point is
  reconciled by relaying the outbox again.
- **The row carries its own org.** The relay and the sweep run with no
  principal and read the org off the row.
