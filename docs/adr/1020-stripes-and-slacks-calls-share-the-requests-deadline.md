# ADR 1020: Stripe's and Slack's calls share the request's deadline

**Status**: accepted (2026-10-14)

## Context

[ADR 0069, A request has a deadline its provider calls share](0069-a-request-has-a-deadline-its-provider-calls-share.md)
gives each request one deadline, which every provider call it makes
keeps to. Tadas's requests also call Stripe and Slack:

| Provider | Attempts | A call gives up after, at most |
|----------|----------|--------------------------------|
| Stripe | 3 | 31.5 seconds |
| Slack | 1 | 10 seconds (21.5 when the connection drops first) |

A Slack uninstall makes two calls to Secrets Manager and one to Slack.

## Decision

**A call takes the deadline exactly when a request can make it:** the
processor's customer, checkout, portal, and cancel; and Slack's install
exchange, uninstall, and revoke. Stripe and Slack take their timeout
per client, not per call, so the cut at the deadline bounds the attempt
in flight.

**The refusal is the one a provider that does not answer already
gets.** Stripe raises `BackendUnreachable`, `503 unavailable`. Slack
raises `SlackFailed`, and the install's callback sends the browser to
the settings page with `slack=failed`, which asks the person to add
Tadas to Slack again. It does the same when the org's secrets did not
take the token in time.

## Consequences

With every provider hanging, at the default timeouts:

| Route | Calls in turn | Without a deadline | With it |
|-------|---------------|--------------------|---------|
| `POST /v1/billing/checkout` | Stripe customer (the first), price, session | 94.5 s | 20 s |
| `POST /v1/billing/portal` | Stripe configurations (the first per process), session | 63 s | 20 s |
| `POST /v1/billing/cancel`, `/resume` | Stripe update | 31.5 s | 20 s |
| `GET /webhooks/slack/oauth` | Slack exchange, Secrets Manager create (and put when it exists) | 140 s; 280 s when it replaces a workspace | 20 s |
| `DELETE /v1/slack/installation` | Secrets Manager read, Slack uninstall, Secrets Manager delete | 140 s | 20 s |
| `POST /webhooks/stripe`, `/webhooks/slack/commands`, `/webhooks/slack/events` | SQS send (and the queue's address, the first per process) | 130 s | 20 s |

The webhook routes take the request stage, as the identity provider's
does, so the OpenAPI document names their `x-app` and `x-app-version`
headers.
