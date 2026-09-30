# ADR 0006: While Tadas has no customer, a deprecated field leaves `/v1`

**Status**: accepted (2026-09-18)

## Context

NET-23 (The Network Layer, Public Types) says a view inside `/v1` only
gains fields, and a removal or a rename is a new prefix. The API's only
consumers are the clients in this repository: the portal, the command
line, and the Python client. Each ships with the API, so no caller
outside the tree holds a field the tree stopped sending.

## Decision

While Tadas has no customer, the API keeps `/v1`, and a field may leave
it one release after it is marked deprecated, where NET-23 asks for
`/v2`.

The first customer, or the first client outside this repository, ends
it: from then on NET-23 holds, and a removal or a rename is `/v2`.

A migration has no such room. Every migration is compatible with the
release before it, and a column moves by add, backfill, switch, and
drop across releases
([ADR 0038](0038-a-dead-column-leaves-the-mapping-before-the-table.md)).

## Consequences

`EventView` names an event by `kind` and `target_id` under `/v1`.
Reviews treat a field that leaves `/v1` as the recorded exception, not
as the pattern: it is marked deprecated for a release first, and the
clients in the tree stop reading it in that release.
