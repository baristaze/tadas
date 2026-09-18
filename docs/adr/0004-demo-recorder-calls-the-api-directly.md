# ADR 0004: The demo recorder calls the API without a generated client

**Status**: accepted (2026-09-18)

## Context

NET-15 (The Network Layer, Clients Live in One Place) says: "A service is
accessed in exactly one way, so each language has one client for it, in
one place, built from the committed OpenAPI document: one generated type
set for a TypeScript app and one typed client package for Python
consumers." `scripts/record_demo.py`, which records the README's
realtime GIF, signs two people in and empties the task list with a few
`urllib.request` calls against `/v1/*`. It is the only Python code that
calls the API; the TypeScript client under `clients/api-client/` is the
one client generated from the committed document. A generated Python
client would exist for one local script that is never deployed, never
imported, and runs against a `make up` stack on the developer's machine.

## Decision

The demo recorder keeps its own six-line request helper and cites this
record. No Python client is generated for it. The first Python consumer
of the API that ships (the CLI the guideline describes, or a service
that calls this one) brings the generated client package with it, under
`clients/`, and the recorder switches to that client in the same change.
Until then the recorder stays the only Python caller and lives under
`scripts/`, not under `clients/`.

## Consequences

A change to the login, session, or tasks routes can break the recorder
without a type error; `make demo-gif` fails at the first call instead,
which is acceptable for a tool run by hand. Reviews treat the `Api`
class in `scripts/record_demo.py` as the documented exception to NET-15
and refuse a second hand-rolled Python caller anywhere else.
