# ADR 1007: The demos are recorded on a local stack, signed in by address

**Status**: accepted (2026-10-14)

## Context

[ADR 0029, A local sign-in by address alone, refused in a deployed environment](0029-a-local-sign-in-by-address.md)
gives the callers that have no browser a person without the identity
provider's round trip.
[ADR 0020, The CLI signs in as a person and holds one auth session](0020-the-cli-signs-in-as-a-person.md)
has `tadas login --dev-email` keep that auth session in a file.

Tadas's README and its site show recorded demos: two portal windows
that follow one list live, and the command line beside `tadas listen`.
A recorder has no browser to sign in with and no mailbox.

## Decision

The demo recorders are callers of the local sign-in.

- `scripts/record_demo.py` (`make demo-gif`, `make demo-gif-dark`)
  signs two seeded people in by address over the Python client, and
  drives the portal in two headless browser contexts.
- `scripts/record_cli_demo.py` (`make demo-cli-gif`) runs the command
  line as real subprocesses. Bob signs in on screen with
  `tadas login --dev-email`, and his commands run under the auth
  session it keeps. The owner's `tadas listen` runs on an auth session
  token the recorder takes over the Python client.

Each records against a running local stack, in the seeded team org,
and empties its task list first.

## Consequences

A demo is never recorded against staging or production: a deployed
process refuses the local sign-in. So a recording shows only seeded
people, and nothing of a real tenant. Recording again needs the local
stack up and seeded.
