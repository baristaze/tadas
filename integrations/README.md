# Integrations

The third-party providers Tadas talks to. Each is one interface with a
real client and a deterministic twin, and a caller never knows which it
holds. Nothing here imports the object model; a provider's errors root
at infra's exception family, since a provider is a dependency the way a
backend is.

## Payments

The payment processor is Stripe. It owns money, customers, and
subscriptions; Tadas owns what a plan entitles an org to.
`PaymentsInterface` is the one door to it:

- a customer per org, made once, carrying the org in its metadata;
- a hosted checkout that starts a subscription to a price named by its
  lookup key, at a quantity;
- a Billing Portal session, the processor's own page for payment
  methods, invoices, a change of plan, and cancellation;
- the two changes Tadas makes to a subscription itself: cancel at the
  period's end (or take that back), and the seat count, with no
  proration;
- a read of a subscription as the processor holds it now. Deliveries
  arrive in any order, so the mirror is written from this read and
  never from a delivery's payload;
- the check of an inbound delivery: the SDK's own signature check over
  the body and its timestamp, inside a five-minute window, answering the
  event's id, type, and the ids it names, and a key for it, a UUID v5
  over the processor's name and the event id.

| Implementation | What it is |
|----------------|------------|
| `PaymentsStripeImpl` | The SDK over one client opened at start, with the account in `Stripe-Context`, `Stripe-Version` pinned to the SDK's release, and a timeout on every call. At start it reads one item under each permission of the runtime key, and names in the start line and the log any resource the key cannot read. Without a key it is unconfigured: every call answers `billing_unavailable` (503). |
| `PaymentsTwinImpl` | Customers, checkouts, and subscriptions in memory. It signs its own deliveries with the processor's scheme, so they pass the same check, and it lets a test complete a checkout, move a subscription, end a period, and have any event delivered. Every id it makes carries `twin`. |

## The catalog

`PaymentsCatalogInterface` is what the operator's bootstrap reconciles:
products, prices by lookup key, the webhook endpoint, and the Billing
Portal configuration. Its caller is `tadas-ops stripe-bootstrap`, never
a serving process, and it runs under a key of its own: the bootstrap
key the person holds, never the runtime key. `payments.permissions`
lists what each key may touch, as Stripe's editor names it.
`CatalogStripeImpl` is the real one, under the same headers and
timeout; `CatalogTwinImpl` keeps the processor's rules that
matter to a reconcile (one price holds a lookup key, a transfer moves
it, an endpoint's secret is shown once) and is what the bootstrap's
tests run against. [The runbook](../docs/runbooks/providers/stripe.md) says how it
is run.

## What a process refuses at boot

- The twin anywhere but `local` and `test`.
- A key that is not a restricted key. An organization key reaches
  every account of the organization, and a secret key may do
  everything in one.
- A key whose mode is not the environment's: production takes a live
  key, every other environment a test key. The prefix says which.
- `TADAS_STRIPE_ORG_KEY`, the runtime key's retired name. The refusal
  names the two that replaced it.

Each refusal names the setting. The settings are `TADAS_BILLING_BACKEND`
(`twin` or `stripe`), `TADAS_STRIPE_ACCOUNT_ID`, `TADAS_STRIPE_RUNTIME_KEY`,
`TADAS_STRIPE_WEBHOOK_SECRET`, and `TADAS_STRIPE_TIMEOUT_SECONDS`; the
two secrets reach a deployed process at start, and `off` or empty leaves
billing unconfigured.

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
Tests never reach Slack. The app's settings, its scopes, and its two
tokens are in [the Slack runbook](../docs/runbooks/providers/slack.md).

## The identity provider

| What | Interface | Real client | Twin |
|------|-----------|-------------|------|
| Proves who a person is: the hosted sign-in, the code exchange, the device sign-in for the command line; and holds an org's side of it: its organization, its single sign-on, its invitations | `identity.IdentityProviderInterface` | `identity/workos.py`: WorkOS AuthKit through the `workos` SDK, pinned | `identity/twin.py`: in memory, for tests and CI |

`identity/absent.py` is the provider of a process that signs nobody in:
every call answers `ProviderUnavailable`, which the API presents as
`503`. The worker holds it, and so does an API whose WorkOS application
key is not set.

The provider hands Tadas an issuer, a subject, and a verified email.
Everything else (the identity row, its id, the sessions, the
memberships) is Tadas's own; the tenancy namespace's README says how a
sign-in becomes a person.

## Settings

| Setting | What |
|---------|------|
| `TADAS_IDENTITY_PROVIDER` | `workos`, `twin`, or `none` (the default). `twin` is refused at boot outside `local` and `test`. |
| `TADAS_WORKOS_CLIENT_ID` | The Tadas App application's client id. Not a secret: every authorization URL carries it. Staging's Tadas App serves the local stack and staging; production has its own. |
| `TADAS_WORKOS_API_KEY` | The Tadas App application's API key, made on that application's own API keys tab, never the environment's API Keys page. A secret, and the process's one WorkOS credential: the client secret of the code exchange (which sends the PKCE verifier as well), and the key of every management call (organizations, invitations, the admin portal), so an invitation carries the application's context. The device sign-in sends no secret. At start the client proves it is the application's key and refuses to boot on any other (ADR 0033). Locally from `.env` or the shell; deployed, injected into the API from the secret store (`<prefix>workos_api_key`). Empty or `off` means not configured: the process starts, says so, and every sign-in through WorkOS answers `503`. |
| `TADAS_WORKOS_BASE_URL`, `TADAS_WORKOS_TIMEOUT_SECONDS` | Where the client calls, and the timeout on every call (10 seconds). |

The WorkOS environments, the application's redirects, and the key are
set up as [the WorkOS runbook](../docs/runbooks/providers/workos.md)
says.

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
