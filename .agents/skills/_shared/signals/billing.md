# Signals: billing

The org's plan and its subscription at the payment processor (Stripe),
mirrored from the processor's deliveries, and the seat count a per-seat
plan bills.

## Kinds

- `SYNC_SEATS`: a per-seat plan's quantity follows the org's active
  members, read when it runs, with no proration and under a key made of
  the item's claim and the count. While the processor is out of reach, or
  refuses the system's key, the item parks and spends no attempt; one
  the processor refuses for the request itself fails at once. One that
  failed for good leaves the subscription billing the old count until
  the next change of members asks again.

## Log lines

Each line names the secret it points to; the secret's value is never
read.

- `payments=stripe (not configured)` on a start line, or
  `billing_unavailable` (503) on a request: checkouts answer 503 and
  every org keeps its plan. `tadas/<env>/stripe_runtime_key` is `off`,
  or the process started before it was written.
- `payments=stripe (acct_..., <version>; the key lacks <resource>,
  ...)` on a start line names what the runtime key could not read at
  start, and `the stripe runtime key lacks <resource> (group <group>)`
  says where the dashboard's editor keeps it. The person adds it to the
  key, which takes effect at once.
- `payments_key_refused` (503) on a request, or `stripe refused the
  runtime key for <call>` at `ERROR` in either log group: the same key
  refused on a call while the process runs, revoked or without that
  permission. Work that made the call stays parked until the key is
  fixed.
- A `503` on `/webhooks/stripe` in the access lines of
  `/tadas/<env>/api`: `tadas/<env>/stripe_webhook_secret` is `off`. A
  `400` there is a signing secret that does not match the endpoint's,
  and the processor retries each delivery. A delivery the API checked
  rides the webhooks queue, and the worker counts it under
  `deliveries`.
- `delivery <id> names org <org>, which has no customer here` or `names
  customer <id>, not org <org>'s` at `WARNING` in
  `/tadas/<env>/maintenance`: one delivery about a customer this
  environment does not hold, mirrored nowhere. Not a finding about a
  secret.

A finding about a secret names the secret and
`docs/runbooks/providers/stripe.md`.

## Search

`payments=stripe|billing_unavailable|payments_key_refused|refused the runtime key|webhooks\/stripe (400|503)`

## Report

Locally, where a laptop runs the processor's twin by design
(`payments=twin`), the line is `- Billing: the twin`, and it names no
secret. Otherwise:

```markdown
- Billing: <configured | off: tadas/<env>/stripe_runtime_key | lacks <resources> | key refused: tadas/<env>/stripe_runtime_key | not in the window>, webhook <configured | off: tadas/<env>/stripe_webhook_secret | signature refused: tadas/<env>/stripe_webhook_secret | not in the window>
```
