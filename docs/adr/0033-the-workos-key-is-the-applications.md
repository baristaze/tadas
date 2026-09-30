# ADR 0033: The WorkOS key is the application's, never the environment's

**Status**: accepted (2026-09-23). Supersedes, in
[ADR 0028](0028-sign-in-is-the-identity-providers.md), that the exchange
is PKCE and not a secret.

## Context

A WorkOS environment holds several applications. WorkOS makes one when
it makes the environment, the default application. Tadas signs people in
through another, the "Tadas App" (staging
`client_01M3640D8WBF9KC0P89YW4E72N`, production
`client_01M363XVP5FGF2P45FHK9B7MJD`). Each application has its
own client id, redirect list, session settings, and API keys, on its
own API keys tab.

The key on the environment's API Keys page is the default
application's. Used as the Tadas App's client secret, the code exchange
answers `invalid_client`. Used for a management call, it runs in the
default application's context: an invitation sent with it lands its
person in the default application, not in Tadas.

## Decision

**The key is the Tadas App application's.** Each Tadas environment holds
one WorkOS credential: an API key made on the Tadas App's own API keys
tab, in the WorkOS environment it signs in through. The setting is
`TADAS_WORKOS_API_KEY`, and the secret is `tadas/<env>/workos_api_key`.

**The code exchange is a confidential client's.** The API holds a
secret, so it sends the application's key as the client secret. Every
management call (organizations, invitations, the Admin Portal link)
carries the same key. One SDK client holds it, with the client id.

**PKCE stays on the browser's sign-in.** The start answers a verifier,
AuthKit sees only its digest, and the exchange sends the verifier
beside the secret. RFC 9700 asks for PKCE on confidential clients too:
it binds a code to the tab that started the sign-in, so a code taken
from the redirect is worth nothing alone.

**The device sign-in stays a public client's.** WorkOS's device flow
takes no client secret. The command line talks only to the API, and
the API makes both calls with the same client.

**The API proves the key before it serves.** At start it exchanges a
code WorkOS never issued, with the key as the client secret. WorkOS
answers `invalid_grant` for the application's key and `invalid_client`
for any other: the environment's key, another application's, or a key
of the other WorkOS environment. On `invalid_client` the API refuses to
start and names the application and the tab the key lives on. A WorkOS
out of reach does not stop the start: the log says the key is not
proven, and a sign-in answers `503`. `tadas-ops workos-bootstrap` makes
the same check first and stops on it.

**The bootstrap writes the application's redirect list.** With the
application's key, WorkOS's redirect URI API reads and writes that
application's list. The bootstrap adds a missing redirect under
`--apply`. The default redirect and the tab's other fields have no API,
so the bootstrap prints each as a check.

## Consequences

An invitation Tadas sends carries the Tadas App's context, and its person
lands on the Tadas App's login initiation URI.

A key from the environment's page stops the API at start. So does a
staging key in production, and a production key in staging: each is
another application's key.

The start makes one call to WorkOS and creates nothing there.

Rotating the key is rotating the application's: make a new key on the
same tab, write it, roll the API, then revoke the old one.
