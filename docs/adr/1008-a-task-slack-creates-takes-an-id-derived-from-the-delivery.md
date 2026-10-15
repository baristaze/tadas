# ADR 1008: A task Slack creates takes an id derived from the delivery

**Status**: accepted (2026-10-14)

## Context

[ADR 0027, What a delivery creates takes an id derived from it](0027-what-a-delivery-creates-takes-an-id-derived-from-it.md)
names one caller of `derived_id`, the identity provider's webhook.
Tadas has a second: Slack's `/tadas add <title>` creates a task.
Slack's calls arrive over HTTP
([ADR 0035](0035-slack-is-a-distributed-app-over-http-installed-per-org.md)):
the API checks each one, acknowledges it, and queues it, and a worker
creates the task.

## Decision

The task's id is `derived_id(key, at)`.

- **The key is Slack's own id for the delivery.** It is a UUID v5 over
  the provider's name and the `trigger_id` of a command, or the
  `event_id` of an event, derived in `tadas.integrations.slack.requests`.
- **The time is when the API received the delivery,** not when Slack
  made it. The API stamps it on the queued item, so every handling of
  that item derives the same id.

The create treats an id it has seen as a retry and answers the row as
stored, so a second handling of the delivery creates nothing.

## Consequences

The task carries its own key, with no marker table and no column, and
its id still sorts by time. The queue's redeliveries of a command make
one task.
