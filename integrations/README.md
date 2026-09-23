# Integrations

The third-party providers Tadas talks to. Each is one interface with a
real client and a deterministic twin, and a caller never knows which it
holds. Nothing here imports the object model; a provider's errors root
at infra's exception family, since a provider is a dependency the way a
backend is.

## Slack

`tadas.integrations.slack.SlackInterface` posts a message, replies in a
thread, answers a slash command through the `response_url` Slack sent
with it, and publishes the App Home. Its errors are the decisions a
caller needs, not Slack's whole vocabulary:

| Error | Means | What the worker does |
|-------|-------|----------------------|
| `SlackRateLimited` | Slack asked to wait (429), `retry_after` says how long | Parks the item for that long |
| `SlackChannelUnusable` | `channel_not_found`, `not_in_channel`, `is_archived` | Marks the connection broken |
| `SlackNotConfigured` | This process holds no bot token | Posts nothing, says so in the log |
| `SlackFailed` | Anything else, a transport failure included | Fails the item, which retries |

Three impls:

- `SlackWebImpl`, the real client: the Web API with the bot token,
  over one aiohttp session opened at start, every call under
  `TADAS_SLACK_TIMEOUT_SECONDS`. A reply goes only to a URL under
  `https://hooks.slack.com/`.
- `SlackTwinImpl`, the twin: records every call in memory, fails on
  request so a test can drive the rate limit and the unusable channel,
  and stamps each message `twin.<n>` so a record says where it came
  from. It refuses to run outside `local` and `test`.
- `SlackOffImpl`: what a deployed process holds with no bot token. It
  posts nothing and says why.

The worker picks one at boot: the real client when a bot token is set,
the twin in a local process without one, and the off impl otherwise.
Tests never reach Slack.

## The identity provider

| What | Interface | Real client | Twin |
|------|-----------|-------------|------|
| Proves who a person is: the hosted sign-in, the code exchange, the device sign-in for the command line; and holds an org's side of it: its organization, its single sign-on, its invitations | `identity.IdentityProviderInterface` | `identity/workos.py`: WorkOS AuthKit through the `workos` SDK, pinned | `identity/twin.py`: in memory, for tests and CI |

`identity/absent.py` is the provider of a process that signs nobody in:
every call answers `ProviderUnavailable`, which the API presents as
`503`. The worker holds it, and so does an API whose WorkOS key is not
set.

The provider hands Tadas an issuer, a subject, and a verified email.
Everything else (the identity row, its id, the sessions, the
memberships) is Tadas's own; the tenancy namespace's README says how a
sign-in becomes a person.

## Settings

| Setting | What |
|---------|------|
| `TADAS_IDENTITY_PROVIDER` | `workos`, `twin`, or `none` (the default). `twin` is refused at boot outside `local` and `test`. |
| `TADAS_WORKOS_CLIENT_ID` | The WorkOS application's client id. Not a secret: every authorization URL carries it. Staging's application serves the local stack and staging; production has its own. |
| `TADAS_WORKOS_API_KEY` | The WorkOS environment's API key, a secret, for the management calls: organizations, invitations, the admin portal. The sign-in's code exchange does not use it: it presents the PKCE verifier the sign-in started with, as the application's public client. Locally from `.env` or the shell; deployed, injected into the API from the secret store (`<prefix>workos_api_key`). Empty or `off` means not configured: the process starts, says so, and every sign-in through WorkOS answers `503`. |
| `TADAS_WORKOS_BASE_URL`, `TADAS_WORKOS_TIMEOUT_SECONDS` | Where the client calls, and the timeout on every call (10 seconds). |

## What every integration holds to

- **A timeout on every call.** The real client builds its own HTTP
  client with the timeout from settings and hands it to the SDK.
- **One exception family.** Every provider error is translated into an
  integration exception, each a leaf of infra's (`ProviderUnavailable`
  is a `503`, `ProviderRefused` a `400`, `ProviderConflict` a `409`),
  and the one caller translates the sign-in leaves into the platform's
  own. The key never appears in a message.
- **A twin that says it is one.** Every id the twin mints starts with
  `twin_`, and the configured root refuses it in a deployed
  environment.
