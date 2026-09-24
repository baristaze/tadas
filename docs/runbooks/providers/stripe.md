# Stripe: operating the payment processor

Tadas sells its plans through Stripe. Stripe holds the money, the
customers, and the subscriptions. Tadas holds what a plan lets an org
do. This page is for a person who has never opened Stripe's dashboard:
what lives where, what is set by hand once, what a command sets, and
what to do when it breaks.

The two other providers have pages of their own:
[WorkOS](workos.md) (sign-in) and [Slack](slack.md).

## The levels, and what lives at each

Stripe nests four levels. Every Tadas setting sits on exactly one.

```text
Stripe organization  "Tadas"                       the business; its people and organization keys
|
+-- account  acct_1UIfVX45a2t9JoiY  (sandbox)      test money only: local and staging
|   +-- keys                restricted keys of this account
|   +-- products            Pro, Team, Max
|   +-- prices              by lookup key: tadas.pro.monthly, tadas.team.monthly, tadas.max.monthly
|   +-- webhook endpoint    https://api.staging.tadas.fyi/webhooks/stripe
|   +-- Billing Portal configuration   the one marked tadas_desired_key=portal
|   +-- customers and subscriptions    made by the product, one customer per org
|
+-- account  acct_1UIfTS4Dj4HbbS1T  (live)         real money: production only
    +-- the same objects, for production
```

| Level | What it is | What Tadas keeps there | Who sets it |
|-------|------------|------------------------|-------------|
| Organization | The business. It owns the accounts and the people who may sign in. | The two accounts | A person, once |
| Account | One set of books. The sandbox moves test money, the live account real money. Nothing is shared between them. | Everything below | A person makes it, once |
| Key | A secret that lets a program call Stripe. An **organization key** reaches every account of the organization and must name the account in the `Stripe-Context` header. A **restricted key** belongs to one account and reaches only the resources it was given. | One key per environment, in the environment's secret store | A person, once per environment |
| Products and prices | What is sold, and for how much. A price is found by its **lookup key**, never by its id. The Max price has two volume tiers. | `deployment/stripe/desired-state.json` | `tadas-ops stripe-bootstrap` |
| Webhook endpoint | The URL Stripe posts events to, and the **signing secret** that proves a post came from Stripe. | One per deployed environment | `tadas-ops stripe-bootstrap` |
| Billing Portal configuration | What a customer may do on Stripe's own page: update a card, see invoices, change plan, cancel at the period's end. | One, marked with metadata | `tadas-ops stripe-bootstrap` |
| Customers and subscriptions | One customer per org that ever started a checkout, carrying the org's id in its metadata. | Made by the product | The API and the worker |

The account ids are not secrets. They are committed: in
`deployment/stripe/desired-state.json`, and in each environment's
Terraform root as `stripe_account_id`.

## Which Tadas environment uses which Stripe account

| Tadas environment | Stripe account | Key mode | Webhook endpoint |
|-------------------|----------------|----------|------------------|
| `local` | the sandbox, `acct_1UIfVX45a2t9JoiY` | test | none: `stripe listen` forwards to the laptop |
| `staging` | the sandbox, `acct_1UIfVX45a2t9JoiY` | test | `https://api.staging.tadas.fyi/webhooks/stripe` |
| `production` | live, `acct_1UIfTS4Dj4HbbS1T` | live | `https://api.tadas.fyi/webhooks/stripe` |

Local and staging share the sandbox. They share its products, prices,
and portal configuration too, which is fine: those are the same
everywhere. Each makes its own customers, because each has its own
orgs.

The mode is a rule, not a habit. A process refuses to start with a key
whose mode is not its environment's: production takes a live key, every
other environment a test key. The prefix says which (`sk_live_`,
`rk_live_`, `sk_org_live_`, `rk_org_live_`, and their `test` twins).

## The key: which kind, and what it may do

The code reads one variable, `TADAS_STRIPE_ORG_KEY`. It takes either
kind of key. Every call names the environment's account in
`Stripe-Context` and pins `Stripe-Version`. So an organization key
reaches the right account, and a restricted key names its own.

The choice here is a **restricted key of the environment's account**.
It cannot reach the other account, and it can do only what it was
given. An organization key works too, but it reaches every account. A
mistake in one environment's secret would then reach the other's books.

The key needs these permissions. Everything else stays **None**.

| Resource (as the dashboard names it) | Permission | Used by | The calls |
|--------------------------------------|------------|---------|-----------|
| Customers | Write | the API | create a customer per org, read it |
| Checkout Sessions | Write | the API | start a hosted checkout |
| Customer portal (Billing Portal) | Write | the API, the bootstrap | open a portal session; list, create, and update the portal configuration |
| Subscriptions | Write | the API, the worker | read a subscription, cancel at the period's end or take it back, change the seat count |
| Prices | Write | the API, the bootstrap | find a price by lookup key; create a price, archive the old one |
| Products | Write | the bootstrap | list, create, and update the three products |
| Webhook Endpoints | Write | the bootstrap | list, create, update, and delete the environment's endpoint |

One key serves the running processes and the bootstrap. The processes
never use the last two rows. Splitting it into two keys is possible and
not done: one key per environment is simpler to hold and to rotate.

## First-time setup, by hand

Do these once per environment, in this order. Staging first.

### 1. Check the account is the one the repository names

1. Sign in at [dashboard.stripe.com](https://dashboard.stripe.com).
2. Open the account switcher (top left). It lists the organization's
   accounts. For staging, pick the sandbox.
3. Open **Settings** → **Account details**. The account id there is
   `acct_1UIfVX45a2t9JoiY` for the sandbox, or `acct_1UIfTS4Dj4HbbS1T`
   for live.

If an id differs, stop. Every call names the committed id, so a key of
another account is refused.

### 2. Make the restricted key

1. In the sandbox, open **Developers** → **API keys**.
2. Choose **Create restricted key**. Name it after the environment,
   for example `tadas-staging`.
3. Set each resource in the table above to **Write**. Leave every
   other resource at **None**.
4. Create it. Stripe shows the key once. It starts with `rk_test_`
   (`rk_live_` in the live account). Keep it in your password manager.
   Never paste it into a chat, a ticket, or a file in the repository.

**Check.** The prefix says the mode. The bootstrap's dry run (step 5)
uses the key: a missing permission answers with an error that names the
resource.

### 3. Let the first deploy make the secret containers

The environment's first deploy that carries billing makes two secrets
in the environment's AWS account, each holding the word `off`:

- `tadas/<env>/stripe_org_key`
- `tadas/<env>/stripe_webhook_secret`

`off` means "not set". The processes start, billing is unconfigured,
every org keeps its plan, and a checkout answers `503`.

**Check**, under your own sign-in:

```bash
aws secretsmanager describe-secret --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/stripe_org_key --query '{name: Name, changed: LastChangedDate}'
```

It answers with the name. `ResourceNotFoundException` means the deploy
has not run yet: wait for it. A value written before the container
exists makes a secret Terraform does not own, and the next deploy fails
on it.

### 4. Write the key into the secret store

Keys exported in the shell outrank a profile, so clear them first.
`read -rs` takes the value without showing it, and keeps it out of the
shell's history:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sso login --profile tadas-staging
read -rs VALUE    # paste the key, press Enter; nothing is shown
aws secretsmanager put-secret-value --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/stripe_org_key --secret-string "$VALUE"
unset VALUE
```

The answer names the secret and a new `VersionId`. It never shows the
value.

### 5. Run the bootstrap: products, prices, portal, endpoint

The bootstrap makes the account match the committed definition. It
reads the key from the shell. It writes the endpoint's signing secret
straight into `tadas/<env>/stripe_webhook_secret`, under your sign-in
profile (`tadas-staging` for staging), and never prints it. Run it from
the repository, dry first:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
read -rs TADAS_STRIPE_ORG_KEY && export TADAS_STRIPE_ORG_KEY
uv run tadas-ops stripe-bootstrap --env staging --dry-run
uv run tadas-ops stripe-bootstrap --env staging
uv run tadas-ops stripe-bootstrap --env staging    # again
unset TADAS_STRIPE_ORG_KEY
```

The first line names the account, the API version, and where the
secret goes. Then one line per object, and a count:

```text
created    product                tadas.pro
created    price                  tadas.pro.monthly
...
created    webhook endpoint       webhook.staging  (we_..., https://api.staging.tadas.fyi/webhooks/stripe)
```

Each line says `created`, `updated`, `unchanged`, `archived`, or
`rolled`. The third run changes nothing and says so:

```text
no changes: acct_1UIfVX45a2t9JoiY matches the desired state for staging
```

**Check** in the dashboard. **Product catalog** shows Pro, Team, and
Max. **Developers** → **Webhooks** shows the endpoint, listening for
six events. **Settings** → **Billing** → **Customer portal** shows the
configuration.

The command refuses an agent's investigate profile, which writes no
secret.

### 6. Let the processes pick the values up

A task reads its secrets once, when it starts. So the values reach the
API and the worker at the next deploy; the next merge to `main` does
it. To pick them up now, start new tasks of the two services that call
Stripe:

```bash
aws ecs update-service --profile tadas-staging --region us-west-2 \
  --cluster tadas-staging --service api --force-new-deployment
aws ecs update-service --profile tadas-staging --region us-west-2 \
  --cluster tadas-staging --service maintenance --force-new-deployment
```

**Check.** The API's start line in `/tadas/staging/api` names the
payments backend. It reads `payments=stripe (acct_1UIfVX45a2t9JoiY,
<version>)` once the key is in, and `payments=stripe (not configured)`
before. Then open the portal's billing page as an owner and start a
checkout. Stripe's page opens. Pay with the test card
`4242 4242 4242 4242`, any future date, any CVC. Back on the billing
page, the plan changes within a few seconds: the webhook delivery
arrived and the worker applied it.

## What is automated, and by what

| What | Done by | When |
|------|---------|------|
| The two secret containers, holding `off` | Terraform, `deployment/terraform/modules/secrets` | The first deploy that carries them |
| Products, prices (the Max tiers among them), the Billing Portal configuration | `tadas-ops stripe-bootstrap` | A person runs it: once per environment, and after a change to the definition |
| The webhook endpoint, its events, and its signing secret in the secret store | `tadas-ops stripe-bootstrap` | The same run |
| The key and the secret inside the processes | The deploy: each task gets them as environment variables at start | Every task start |
| Customers and subscriptions | The API at checkout, the worker from deliveries | While people use the product |

The key itself is never automated. A person makes it and writes it.

The bootstrap finds its objects by lookup key and by metadata
(`tadas_managed=true`, `tadas_desired_key`). So it never makes a second
copy, and it leaves everything else in the account alone.

A price never changes in place. A new amount is a new price that takes
the lookup key over, and the old price is archived. Subscriptions on
the old price keep it until they change plan. The portal configuration
is updated to offer the new one.

## Local development

The laptop uses the sandbox, like staging.

1. Export the sandbox key in the shell you run `make up` in, or set it
   in `.env`, which git ignores:

   ```bash
   read -rs TADAS_STRIPE_ORG_KEY && export TADAS_STRIPE_ORG_KEY
   make up
   ```

   `.env.example` leaves `TADAS_STRIPE_ORG_KEY` and
   `TADAS_STRIPE_WEBHOOK_SECRET` commented out on purpose. The Makefile
   includes that file, and a line there with an empty value would
   override what the shell exported.

2. Stripe cannot reach a laptop, so `local` has no endpoint. Forward
   the deliveries with the Stripe CLI instead. It prints a signing
   secret of its own (`whsec_...`):

   ```bash
   stripe login                      # once; choose the sandbox
   stripe listen --forward-to http://127.0.0.1:8000/webhooks/stripe
   ```

   Export that secret as `TADAS_STRIPE_WEBHOOK_SECRET` and restart the
   API. A checkout on the laptop now changes the org's plan.

Without the CLI, a delivery can be made by hand: sign the body with the
local secret the way `tadas.integrations.payments.deliveries.sign`
does, and post it to the same route. The tests do that.

## Rotation

**The key.** Make a new restricted key with the same permissions (step
2). Write it (step 4). Roll the two services (step 6). Check the start
line. Then delete the old key under **Developers** → **API keys**. Both
work until then, so nothing breaks in between.

**The webhook signing secret.** Stripe shows it only when an endpoint
is made, so a rotation is a new endpoint. Write `off` into the secret,
then run the bootstrap. It finds the store empty, deletes the endpoint,
makes it again, and stores the new secret:

```bash
aws secretsmanager put-secret-value --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/stripe_webhook_secret --secret-string off
uv run tadas-ops stripe-bootstrap --env staging
```

The endpoint's line reads `rolled`. Roll the API (step 6). A delivery
sent in the minutes between fails its check, and Stripe sends it again
later, so nothing is lost.

## When it breaks

| What you see | Why | Where to look |
|--------------|-----|---------------|
| A checkout or the portal answers `503` `billing_unavailable` | The key is `off` or empty, or the task started before it was written | The API's start line in `/tadas/<env>/api`: `payments=stripe (not configured)` |
| The API or the worker does not start, and the deploy rolls back | A key of the wrong mode: a live key in staging, or a test key in production. The boot check refuses it | `/tadas/<env>/api` and `/tadas/<env>/maintenance`; the refusal names the setting |
| Stripe shows failed deliveries answered `400` | The signing secret does not match the endpoint's | Stripe: **Developers** → **Webhooks** → the endpoint → its deliveries. Roll the secret as above |
| Failed deliveries answered `503` | `tadas/<env>/stripe_webhook_secret` is `off` | The same page. Run the bootstrap, then roll the API |
| A plan does not change after a paid checkout | The worker could not apply the delivery | `/tadas/<env>/maintenance`, and the queue `tadas-<env>-webhooks-dead`, where a delivery lands after its retries |
| A call fails with a permission error naming a resource | The key lacks that permission | Add it to the key in the dashboard. It takes effect at once |

Stripe retries a failed delivery on its own, with a growing delay: for
up to three days in live mode, and for less in a sandbox. Tadas reads
the subscription from Stripe on every delivery rather than trusting the
delivery's body, so a late or out-of-order delivery does no harm.

To read the dead-letter queue's depth, under the investigate profile:

```bash
aws sqs get-queue-attributes --profile tadas-staging-investigate --region us-west-2 \
  --queue-url "$(aws sqs get-queue-url --profile tadas-staging-investigate --region us-west-2 \
    --queue-name tadas-staging-webhooks-dead --query QueueUrl --output text)" \
  --attribute-names ApproximateNumberOfMessages
```

## When an environment is torn down

`scripts/cloud_nuke.sh` destroys the environment in AWS. It does not
touch Stripe, and it lists what stays there:

- **The webhook endpoint** for the environment's API name. Stripe keeps
  posting to a name that no longer answers, and mails about the
  failures after a while. If the environment comes back, leave it: the
  new secret store holds `off`, so the next bootstrap rolls the
  endpoint and stores a fresh secret. If it does not come back, delete
  it under **Developers** → **Webhooks**.
- **The customers and subscriptions** its orgs made. In the sandbox
  they are test data, and harmless.
- **The key.** The secret that held it is gone, so a recreated
  environment needs it written again (step 4).

## Production (parked)

Production is not running yet. When it is, the steps are the same, with
these differences:

- The account is the live one, `acct_1UIfTS4Dj4HbbS1T`, and the key
  starts with `rk_live_`. Make it in the live account, not the
  sandbox.
- The everyday production profile, `tadas-prod`, only reads. Writing a
  secret and rolling a service need `tadas-prod-power`, and only when
  that change is explicitly authorized. Use it for steps 3, 4, and 6,
  and pass it to the bootstrap, which otherwise uses `tadas-prod`:

  ```bash
  uv run tadas-ops stripe-bootstrap --env production --profile tadas-prod-power --dry-run
  uv run tadas-ops stripe-bootstrap --env production --profile tadas-prod-power
  ```

- The live account needs its business details and a bank account
  before Stripe lets it charge a card. The dashboard asks for them
  under **Settings**.
- Test once with a real card, then refund it from the dashboard.

What must never happen:

- **A live key in staging or on a laptop.** The boot check refuses it,
  and the deploy rolls back. Do not look for a way around it.
- **A test key in production.** Refused the same way.
- **A key in the repository, a chat, a ticket, or a log.** The key's
  name is enough everywhere. The value lives in the password manager
  and the secret store only.
