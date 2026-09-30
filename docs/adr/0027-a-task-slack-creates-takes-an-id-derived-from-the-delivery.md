# ADR 0027: A task Slack creates takes an id derived from the delivery

**Status**: accepted (2026-09-22)

## Context

OM-12 (Identifiers): "Every id is `uuid_v7`, minted above storage with
`new_id()`, or with `derived_id()` from a key that names the record, so
a second run makes the same id." Idempotency on the Consumer Side says a message from
outside carries a key derived from the provider's delivery, a UUID v5
over the provider's name and its delivery id, and the handler dedupes
on it. The key lives on the row the effect produces, or the marker and
the effect are one atomic write.

The queue is at least once, so the same delivery can reach its handler
twice. A marker in a table of its own would be a second write beside
the effect.

## Decision

A record an outside delivery creates takes an id derived from the
delivery: `derived_id(key, at)` in `tadas.om.base`. It is a v7 whose time
is `at` and whose random bits come from the key. The key is the
delivery's UUID v5, and `at` is when the provider made the delivery.

It has two callers. One is Slack's command: `/tadas add <title>` creates
a task. Slack's calls arrive over HTTP
([ADR 0035](0035-slack-is-a-distributed-app-over-http-installed-per-org.md)).
The API checks each one, acknowledges it, and queues it; a worker
creates the task. The key is a UUID v5 over the provider's name and
Slack's own id for the delivery: the `trigger_id` of a command, and the
`event_id` of an event. The module that derives the key is
`tadas.integrations.slack.requests`. The task's `at` is when the API
received the delivery. The create primitive treats an id it has seen as
a retry and answers the row as stored, so a second handling of the
delivery creates nothing.

The other is the identity provider's webhook. The maintenance
worker records each delivery that names an org as an audit entry,
`identity.event.received`
([ADR 0011](0011-audit-entries-are-events.md)), under the derived id.
The append is idempotent on the event's id, so a copy the queue hands
over again appends nothing.

OM-12 names it with what an orchestration step makes
([ADR 0039](0039-long-running-work-is-a-record-a-guard-parks-and-a-bound-fails.md))
as the ids not minted with `new_id()` (Identifiers). Every other id is
`new_id()`.

## Consequences

The effect carries its own key, with no marker table and no column. The
id still sorts by time and still reads as a v7.

The id's random bits are not random: anyone who knew a delivery's key
and its time could compute the id. Neither leaves the platform, and an
id is never a credential.

A new provider whose deliveries create records uses the same function
with its own key.
