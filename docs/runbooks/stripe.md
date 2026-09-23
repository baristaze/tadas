# The payment processor's account

Tadas sells three plans through Stripe. What the account holds for them
is one committed definition, `deployment/stripe/desired-state.json`: the
products, the prices by lookup key (the Max price's two volume tiers
among them), the Billing Portal configuration, the webhook endpoint of
each environment and the events it delivers, and the account each
environment uses. `tadas-ops stripe-bootstrap` makes an account match
it. The object model's pricing rule and this file are held to each
other by `ops/tests/test_stripe_bootstrap.py`, at ten seats and at
eleven.

## The accounts and the credentials

| Environment | Account | Key mode | Webhook endpoint |
|-------------|---------|----------|------------------|
| `local` | the sandbox, `acct_1UIfVX45a2t9JoiY` | test | none: `stripe listen` |
| `staging` | the sandbox, `acct_1UIfVX45a2t9JoiY` | test | `https://api.staging.tadas.fyi/webhooks/stripe` |
| `production` | live, `acct_1UIfTS4Dj4HbbS1T` | live | `https://api.tadas.fyi/webhooks/stripe` |

Every call names the account in `Stripe-Context` and pins
`Stripe-Version` to the version the SDK was released against. The
account id is not a secret and is committed. Two values are: the key,
and the endpoint's signing secret. A deployed process gets both at start
as process credentials, like the database URLs:

| Secret in the environment's account | Reaches the process as |
|-------------------------------------|------------------------|
| `tadas/<env>/stripe_org_key` | `TADAS_STRIPE_ORG_KEY` |
| `tadas/<env>/stripe_webhook_secret` | `TADAS_STRIPE_WEBHOOK_SECRET` |

A process refuses to start with a key whose mode is not its
environment's: production takes a live key, every other environment a
test key. The prefix says which (`sk_live_`, `rk_live_`, `sk_org_live_`,
and their `test` twins). A secret still reading `off` leaves billing
unconfigured: the plans hold, and nobody can buy one there.

## Bootstrap an environment

Under your own sign-in, with the account's key in the shell and nothing
else:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export TADAS_STRIPE_ORG_KEY=...          # the environment's key, from your password manager
uv run tadas-ops stripe-bootstrap --env staging --dry-run
uv run tadas-ops stripe-bootstrap --env staging
uv run tadas-ops stripe-bootstrap --env staging   # again: "no changes"
```

Each line of the output is one object: `created`, `updated`,
`unchanged`, `archived`, or `rolled`, then a summary. The run finds its
objects by lookup key and by metadata (`tadas_managed=true`,
`tadas_desired_key`), so it never makes a second one.

A price never changes in place. A changed amount is a new price that
takes the lookup key over (`transfer_lookup_key`); the old one is
archived, and subscriptions on it keep it until they change plan. The
portal configuration is updated to offer the new price.

## The webhook endpoint's secret

Stripe shows an endpoint's signing secret once, when the endpoint is
made. The run writes it straight to `tadas/<env>/stripe_webhook_secret`
in the environment's account, under the sign-in profile
`deployment/cloud/environments.json` names (`tadas-staging` for
staging), and never prints it. The services pick it up on their next
rollout.

The secret is lost when that store holds nothing for it, or `off`. The
run then rolls the endpoint: it deletes it, makes it again, and stores
the new secret. Deliveries in flight to the old endpoint are retried by
Stripe against nothing, so the subscriptions they are about are read
again on the next delivery; nothing is lost but a few minutes.

`--secret-store none` writes to no store. A create then says the secret
was shown once and kept nowhere; a later run with `--secret-store aws`
finds the store empty and rolls the endpoint to put one there.

## Local runs

Stripe cannot reach a laptop, so `local` has no endpoint. To see real
deliveries against the sandbox, forward them with the Stripe CLI and give
the API the secret it prints:

```bash
stripe listen --forward-to http://127.0.0.1:8000/webhooks/stripe
# TADAS_STRIPE_WEBHOOK_SECRET=whsec_... in .env, then restart the API
```

Without the CLI, a delivery can be made by hand: sign the body with the
local secret the way `tadas.integrations.payments.deliveries.sign` does
and post it to the same route.
