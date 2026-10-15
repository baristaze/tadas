# ADR 1009: Local and staging sign in through the staging Tadas App

**Status**: accepted (2026-10-14)

## Context

[ADR 0033, The WorkOS key is the application's, never the environment's](0033-the-workos-key-is-the-applications.md)
makes each environment's key the Tadas App's own, in the WorkOS
environment it signs in through. WorkOS has environments of its own,
and a WorkOS environment is not a Tadas environment: Tadas has three,
local, staging, and production.

## Decision

| Tadas environment | WorkOS environment | Tadas App client id |
|-------------------|--------------------|---------------------|
| local | Staging | `client_01M3640D8WBF9KC0P89YW4E72N` |
| staging | Staging | `client_01M3640D8WBF9KC0P89YW4E72N` |
| production | Production | `client_01M363XVP5FGF2P45FHK9B7MJD` |

Local and staging share the Staging environment's Tadas App, and
production has its own. Each Tadas environment still holds a key of its
own, made on that application's API keys tab, and accepts only its own
callback. `deployment/workos/environments.yaml` holds each
application's desired state, and `tadas-ops workos-bootstrap`
reconciles WorkOS with it.

## Consequences

A client id is not a secret, and it is committed: in the WorkOS file,
in each Terraform root, and in `.env.example`.

A person who signs in locally through WorkOS is a user of the Staging
environment, beside staging's users. Nothing local reaches production's
WorkOS environment.
