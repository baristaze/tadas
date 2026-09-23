# Integrations

The third-party providers the platform depends on and cannot conjure.
Each is an interface with two implementations: the real client, and a
deterministic twin that speaks the same shapes and runs in memory. The
object model sees the interface; a process picks the implementation
from its settings at boot. Integrations imports infra and nothing from
the object model, and its exceptions hang under infra's root, so the
gateway presents them like any other backend's.

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
| `PaymentsStripeImpl` | The SDK over one client opened at start, with the account in `Stripe-Context`, `Stripe-Version` pinned to the SDK's release, and a timeout on every call. Without a key it is unconfigured: every call answers `billing_unavailable` (503). |
| `PaymentsTwinImpl` | Customers, checkouts, and subscriptions in memory. It signs its own deliveries with the processor's scheme, so they pass the same check, and it lets a test complete a checkout, move a subscription, end a period, and have any event delivered. Every id it makes carries `twin`. |

## The catalog

`PaymentsCatalogInterface` is what the operator's bootstrap reconciles:
products, prices by lookup key, the webhook endpoint, and the Billing
Portal configuration. Its caller is `tadas-ops stripe-bootstrap`, never
a serving process. `CatalogStripeImpl` is the real one, under the same
headers and timeout; `CatalogTwinImpl` keeps the processor's rules that
matter to a reconcile (one price holds a lookup key, a transfer moves
it, an endpoint's secret is shown once) and is what the bootstrap's
tests run against. [The runbook](../docs/runbooks/stripe.md) says how it
is run.

## What a process refuses at boot

- The twin anywhere but `local` and `test`.
- A key whose mode is not the environment's: production takes a live
  key, every other environment a test key. The prefix says which.

Each refusal names the setting. The settings are `TADAS_BILLING_BACKEND`
(`twin` or `stripe`), `TADAS_STRIPE_ACCOUNT_ID`, `TADAS_STRIPE_ORG_KEY`,
`TADAS_STRIPE_WEBHOOK_SECRET`, and `TADAS_STRIPE_TIMEOUT_SECONDS`; the
two secrets reach a deployed process at start, and `off` or empty leaves
billing unconfigured.
