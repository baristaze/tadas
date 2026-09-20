# Events

The org's diary: the append-only stream behind every live push. This
is one of the six kinds of thing [Tadas is made of](../../../../README.md).

## The nouns

- **Event**: one line in the diary. It carries the org, its sequence
  number, its kind, the record that changed, a snapshot of that record,
  when it was produced, and who produced it: the actor, the request,
  and the app the request came from.
- **Kind**: `<namespace>.<entity>.<action>` for a change, such as
  `tasks.task.updated`, or an audit kind for something the platform
  records about itself, such as a job that failed for good.
- **Head**: the sequence number of the last event, zero before the
  first. A screen that opens the live channel starts here.

## What can happen

- **Append.** A change appends its event through the outbox relay. An
  audit entry is appended by the part of the platform that has
  something to record, as itself.
- **Read after a number.** Everything after a sequence number, oldest
  first, so a screen that was away catches up.
- **Read the head.**

Nothing else. No update, no delete.

## The rules

- **The sequence is gapless per org.** Each org has a cursor holding
  its head. An append takes the head plus one under the cursor's lock,
  inside the append's own transaction. Two appends to one org queue on
  the cursor, and an append that rolls back returns the number with
  it. The number is never computed by looking for the largest one and
  hoping.
- **Appending twice appends once.** An append is idempotent on the
  event's id. Relaying an outbox row twice consumes one number and
  leaves one line.
- **A number is spent only by the org's own write.** An id another org
  owns is refused before the number is taken.
- **Provenance is stamped, never claimed.** The actor, the request,
  and the app on an audit entry come from the context the caller
  holds, not from the event the caller sends.
- **A push is a hint; the diary is the truth.** A screen keeps the last
  contiguous number it applied. A push that arrives ahead of it is not
  a skip: it is a replay of the diary from that number.
