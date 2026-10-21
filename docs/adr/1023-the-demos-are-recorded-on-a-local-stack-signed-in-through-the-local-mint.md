# ADR 1023: The demos are recorded on a local stack, signed in through the local mint

**Status**: accepted (2026-10-21)

## Context

[ADR 0104, The local stack signs in through the provider, and machines through a local mint](0104-the-local-stack-signs-in-through-the-provider-and-machines-through-a-local-mint.md)
signs every person in through WorkOS, on every stack, and gives the
callers with no browser and no mailbox a login from the local mint,
`tadas-api mint-local-login`. No route or page signs anyone in by
address.

Tadas's README and its site show recorded demos: two portal windows
that follow one list live, and the command line beside `tadas listen`.
A recorder has no browser to sign in with and no mailbox.

## Decision

The demo recorders are callers of the local mint. Each mints its two
seeded people with one call, exchanges each login for an auth session
in the seeded team org over the Python client, and empties that org's
task list first.

- `scripts/record_demo.py` (`make demo-gif`, `make demo-gif-dark`) puts
  each auth session where the portal keeps it, and drives the portal in
  two headless browser contexts.
- `scripts/record_cli_demo.py` (`make demo-cli-gif`) runs the command
  line as real subprocesses, each with its auth session token in the
  environment: Bob's commands on the left, the owner's `tadas listen`
  on the right. Nobody runs `tadas login` on screen, since its device
  flow needs a browser.

The Makefile names the seeded owner and member, the plus-addresses of
`SEED_EMAIL`, so a recorder takes no address of its own.

## Consequences

A demo is never recorded against staging or production: the mint runs
only on a local database, and refuses at boot elsewhere. So a recording
shows only seeded people, and nothing of a real tenant. Recording again
needs the local stack up and seeded.

The seeded people's addresses are plus-addresses of whoever recorded.
A recording that is committed is made with a base address that may be
public, such as `SEED_EMAIL=dev@example.com`.
