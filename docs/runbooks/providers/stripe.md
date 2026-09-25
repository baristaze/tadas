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
Stripe organization  "Tadas"                       the business; its people
|
+-- account  acct_1UIfVX45a2t9JoiY  (sandbox)      test money only: local and staging
|   +-- keys                tadas-staging-runtime, tadas-local-runtime, tadas-bootstrap-sandbox
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
| Key | A secret that lets a program call Stripe. A **restricted key** belongs to one account and reaches only the resources it was given. Tadas takes nothing else: an **organization key** reaches every account of the organization, and a **secret key** may do everything in its account. | Two restricted keys: a runtime key per environment, in the environment's secret store, and a bootstrap key per account, held by the person who runs the bootstrap | A person, once per key |
| Products and prices | What is sold, and for how much. A price is found by its **lookup key**, never by its id. The Max price has two volume tiers. | `deployment/stripe/desired-state.json` | `tadas-ops stripe-bootstrap` |
| Webhook endpoint | The URL Stripe posts events to, and the **signing secret** that proves a post came from Stripe. | One per deployed environment | `tadas-ops stripe-bootstrap` |
| Billing Portal configuration | What a customer may do on Stripe's own page: update a card, see invoices, change plan, cancel at the period's end. The portal's "Update payment method" button after a failed payment opens the card update directly, which needs the update turned on here. | One, marked with metadata | `tadas-ops stripe-bootstrap` |
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
other environment a test key. The prefix says which: `rk_live_` or
`rk_test_`. The bootstrap refuses the same way.

## The two keys, and what each may do

Tadas holds two **restricted keys** of each account. Each may touch
only what its work needs. Everything else on it stays **None**.

- The **runtime key** serves the running processes: the API and the
  worker. It lives in the environment's secret store,
  `tadas/<env>/stripe_runtime_key`, and reaches the processes as
  `TADAS_STRIPE_RUNTIME_KEY`. One per environment.
- The **bootstrap key** serves `tadas-ops stripe-bootstrap`. The person
  who runs it holds it, in a password manager, and exports it as
  `TADAS_STRIPE_BOOTSTRAP_KEY` in their own shell. It is never written
  to the cloud, and no process reads it. One per account.

Each call names the environment's account in `Stripe-Context` and pins
`Stripe-Version`. A restricted key of another account is refused by
Stripe. An organization key or a secret key is refused by Tadas before
any call: the processes refuse to start, and the bootstrap stops.

Stripe's key editor lists its resources in **groups**, in a column on
the left: Core, Access Management, Accounts v2, Batches, Billing,
Capability Definitions, Checkout Sessions, and so on. Each group has a
switch of its own (None, Read, Write) and a row per resource inside
it. The **Group** column below says where each row sits. If a name
differs from what the editor shows, type the resource into the search
box at the top of the editor, **Search by resource or endpoint**.

> [!WARNING]
> **Checkout Sessions is a group of its own.** Setting Core or Billing
> to Write does not include it. A runtime key without it makes every
> checkout fail with a permission error, while the rest of billing
> works.

### The runtime key: `tadas-<env>-runtime`

| Group | Resource (as the editor names it) | Permission | The calls |
|-------|-----------------------------------|------------|-----------|
| Core | Customers | Write | create a customer per org; read it back when a delivery names it |
| Checkout Sessions | Checkout Sessions | Write | start a hosted checkout |
| Billing | Customer Portal | Write | open a portal session (a write); list the portal configurations to find the one the bootstrap manages (a read, which Write includes) |
| Billing | Subscriptions | Write | read a subscription; cancel it at the period's end or take that back; change the seat count |
| Billing | Prices | Read | find a price by its lookup key |

The API and the worker hold the same key. Both call Customers and
Subscriptions; the API alone starts checkouts and portal sessions.

### The bootstrap key: `tadas-bootstrap-sandbox`, `tadas-bootstrap-live`

| Group | Resource (as the editor names it) | Permission | The calls |
|-------|-----------------------------------|------------|-----------|
| Core | Products | Write | list, create, and update the three products |
| Billing | Prices | Write | list the prices by lookup key; create a price; archive the old one |
| Webhook Endpoints | Webhook Endpoints, Event Destinations | Write | list, create, update, and delete the environment's endpoint |
| Billing | Customer Portal | Write | list, create, and update the portal configuration |

The bootstrap needs no Customers, no Checkout Sessions, and no
Subscriptions. The processes need no Products and no Webhook Endpoints.
Neither key can do the other's work. The same two lists are in the
code, in `integrations/src/tadas/integrations/payments/permissions.py`.

### How a process checks its key

At start, the API and the worker each read one item under every row
of the runtime key's table. The start line names what the key could
not read:

```text
payments=stripe (acct_1UIfVX45a2t9JoiY, <version>; the key lacks Checkout Sessions)
```

and an error line says where the row is:

```text
the stripe runtime key lacks Checkout Sessions (group Checkout Sessions): set it to Write on the key
```

A key refused on every read is revoked, or a key of another account;
the log says so. The check reads, so it proves a row is not **None**.
It cannot prove **Write** without writing. The process starts either
way: billing is one part of it.

## First-time setup, by hand

Do these once per environment, in this order. Staging first.

### 1. Check the account is the one the repository names

The dashboard has three levels, and each has its own settings page:
the organization ("Baris Taze (Personal Projects)"), the account
("Tadas"), and the account's sandbox ("Tadas sandbox"). The account
details, the keys, and the webhooks live on the account and on the
sandbox, never on the organization. When the URL reads
`dashboard.stripe.com/org_…/org/settings`, you are on the
organization's page: it has no **Account details**, and its
**Personal details** → **Accounts** table lists only live accounts, so
the live Tadas account shows there even in sandbox mode, and the
sandbox does not.

The shortest way in is the account's own URL:

- the sandbox, for local and staging:
  [dashboard.stripe.com/acct_1UIfVX45a2t9JoiY/test/apikeys](https://dashboard.stripe.com/acct_1UIfVX45a2t9JoiY/test/apikeys)
- the live account, for production:
  [dashboard.stripe.com/acct_1UIfTS4Dj4HbbS1T/apikeys](https://dashboard.stripe.com/acct_1UIfTS4Dj4HbbS1T/apikeys)

Or by hand: sign in at [dashboard.stripe.com](https://dashboard.stripe.com),
open the switcher at the top left, and pick **Tadas**, then its
sandbox, **Tadas sandbox**.

**Check.** The top left names **Tadas sandbox** (or **Tadas** for
live), and the URL carries the account id: `acct_1UIfVX45a2t9JoiY` and
`/test/` for the sandbox, `acct_1UIfTS4Dj4HbbS1T` and no `/test/` for
live. The same id is under **Settings** → **Business** → **Account
details**. If an id differs, stop. Every call names the committed id,
so a key of another account is refused.

### 2. Make the two restricted keys

Make the runtime key for the environment. Make the bootstrap key once
per account: local and staging share the sandbox, so they share
`tadas-bootstrap-sandbox`.

1. In the sandbox, open **Developers** → **API keys**.
2. Choose **Create restricted key**.
3. Stripe may first ask how the key will be used, or offer a preset
   set of permissions. Choose the option that lets you set each
   permission yourself and starts from none (on some accounts it
   reads **Building your own integration**). Do not choose a preset
   for a third-party app: it adds permissions this key must not have.
4. In **Key name**, type the key's name: `tadas-staging-runtime` for
   staging's runtime key, `tadas-local-runtime` for the laptop's, and
   `tadas-bootstrap-sandbox` for the bootstrap key.
5. Set every group in the left column to **None** first. A duplicated
   key or a preset starts with rows set, and a row left over is a
   permission nobody meant to give.
6. Set the rows of the key's table above, and nothing else. For the
   runtime key, open the **Checkout Sessions** group and set it to
   **Write**: it is not under Core or Billing.
7. Choose **Create key**. Stripe asks for your two-factor code.
8. Stripe shows the key once. Click it to copy it. It starts with
   `rk_test_` (`rk_live_` in the live account). Keep it in your
   password manager. In **Add a note**, write where you kept it, then
   choose **Done**. Never paste the key into a chat, a ticket, or a
   file in the repository.

**Check.** The key list shows the key's name. The prefix says the mode.
The runtime key is checked by the processes at start (step 6). The
bootstrap key is checked by the bootstrap's dry run (step 5): a missing
permission answers with an error that names the resource.

### 3. Let the first deploy make the secret containers

The environment's first deploy that carries billing makes two secrets
in the environment's AWS account, each holding the word `off`:

- `tadas/<env>/stripe_runtime_key`
- `tadas/<env>/stripe_webhook_secret`

The bootstrap key has no secret here. It never goes to the cloud.

A secret in AWS cannot be empty, so Tadas uses the plain word `off`
as a secret's value to mean "not set". Turning a secret off means
replacing its value with that word, and nothing else.

With `off`, the processes start, billing is unconfigured, every org
keeps its plan, and a checkout answers `503`.

**Check**, under your own sign-in:

```bash
aws secretsmanager describe-secret --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/stripe_runtime_key --query '{name: Name, changed: LastChangedDate}'
```

It answers with the name. `ResourceNotFoundException` means the deploy
has not run yet: wait for it. A value written before the container
exists makes a secret Terraform does not own, and the next deploy fails
on it.

### 4. Write the runtime key into the secret store

Keys exported in the shell outrank a profile, so clear them first.
`read -rs` takes the value without showing it, and keeps it out of the
shell's history:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sso login --profile tadas-staging
read -rs VALUE    # paste the runtime key, press Enter; nothing is shown
aws secretsmanager put-secret-value --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/stripe_runtime_key --secret-string "$VALUE"
unset VALUE
```

The answer names the secret and a new `VersionId`. It never shows the
value.

### 5. Run the bootstrap: products, prices, portal, endpoint

The bootstrap makes the account match the committed definition. It
reads the bootstrap key from the shell, and never the runtime key. It writes the endpoint's signing secret
straight into `tadas/<env>/stripe_webhook_secret`, under your sign-in
profile (`tadas-staging` for staging), and never prints it. Run it from
the repository, dry first:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
read -rs TADAS_STRIPE_BOOTSTRAP_KEY && export TADAS_STRIPE_BOOTSTRAP_KEY
uv run tadas-ops stripe-bootstrap --env staging --dry-run
uv run tadas-ops stripe-bootstrap --env staging
uv run tadas-ops stripe-bootstrap --env staging    # again
unset TADAS_STRIPE_BOOTSTRAP_KEY
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
before. A key that lacks a row reads `payments=stripe
(acct_1UIfVX45a2t9JoiY, <version>; the key lacks <resource>, ...)`:
add the row to the key (**Change what an existing key may do**, below)
and roll the two services again. Then open the portal's billing page as an owner and start a
checkout. Stripe's page opens. Pay with the test card
`4242 4242 4242 4242`, any future date, any CVC. Back on the billing
page, the plan changes within a few seconds: the webhook delivery
arrived and the worker applied it.

## Change what an existing key may do

Permissions change in place. The key's secret stays the same, and the
change takes effect at once: there is no secret to write again, and the
next call already has it. The start line still says what the runtime
key lacked when the task started; it clears at the next start.

1. **Developers** → **API keys**, find the key under **Restricted
   keys**.
2. Open the row's menu (**⋯**) and choose **Edit key**.
3. Stripe shows a **Summary** of what the key may do. Choose **Edit**.
4. Set the rows, and save.

The row's menu also has **View request logs**. A request the key was
refused shows there as `403`, with the permission it needed.

## What is automated, and by what

| What | Done by | When |
|------|---------|------|
| The two secret containers, holding `off` | Terraform, `deployment/terraform/modules/secrets` | The first deploy that carries them |
| Products, prices (the Max tiers among them), the Billing Portal configuration | `tadas-ops stripe-bootstrap` | A person runs it: once per environment, and after a change to the definition |
| The webhook endpoint, its events, and its signing secret in the secret store | `tadas-ops stripe-bootstrap` | The same run |
| The runtime key and the signing secret inside the processes | The deploy: each task gets them as environment variables at start | Every task start |
| The runtime key's check: one read per permission | The API and the worker | Every task start |
| Customers and subscriptions | The API at checkout, the worker from deliveries | While people use the product |

The keys themselves are never automated. A person makes each one, and
writes the runtime key into the secret store.

The bootstrap finds its objects by lookup key and by metadata
(`tadas_managed=true`, `tadas_desired_key`). So it never makes a second
copy, and it leaves everything else in the account alone.

A price never changes in place. A new amount is a new price that takes
the lookup key over, and the old price is archived. Subscriptions on
the old price keep it until they change plan. The portal configuration
is updated to offer the new one.

## Local development

The laptop uses the sandbox, like staging.

1. Export the laptop's runtime key, `tadas-local-runtime` (step 2), in
   the shell you run `make up` in, or set it in `.env`, which git
   ignores:

   ```bash
   read -rs TADAS_STRIPE_RUNTIME_KEY && export TADAS_STRIPE_RUNTIME_KEY
   make up
   ```

   `.env.example` leaves `TADAS_STRIPE_RUNTIME_KEY` and
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

Rotate a key when it may have been seen, when the person who holds the
bootstrap key changes, and on the schedule you keep for secrets.

**The runtime key.** Make a new restricted key with the same rows. The
row menu's **Duplicate key** copies them; check the copy against the
table anyway, then name it after the environment again. Write it (step
4). Roll the two services (step 6). Check the start line: no "lacks".
Then, under **Developers** → **API keys**, open the old key's menu (⋯)
and delete it. Both keys work until then, so nothing breaks in between.

**The old secret, `stripe_org_key`.** It held the one key Tadas used
before the runtime key and the bootstrap key. Nothing reads it now, but
it stays in AWS for one more release, for two reasons: Terraform still
owns it, and the release before this one still reads it if it is ever
rolled back to. Once the runtime key works, turn it off:

```bash
aws secretsmanager put-secret-value --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/stripe_org_key --secret-string off
```

Do not delete it. AWS keeps a deleted secret's name for at least seven
days, and the next deploy fails when it tries to make the secret again.
Do not write any other text into it either. A rolled-back release reads
any other value as a key, refuses it, and does not start. The next
release removes the secret from Terraform, and Terraform deletes it.

**The bootstrap key.** Make a new one with the bootstrap's rows, store
it in the password manager, and run the bootstrap's dry run with it.
Then delete the old one. No environment holds it, so nothing is
written and nothing is rolled.

**The webhook signing secret.** Stripe shows it only when an endpoint
is made, so a rotation is a new endpoint. Replace the secret's value
with the word `off`, then run the bootstrap. It finds the store empty, deletes the endpoint,
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
| A checkout or the portal answers `503` `billing_unavailable` | The runtime key is `off` or empty, or the task started before it was written | The API's start line in `/tadas/<env>/api`: `payments=stripe (not configured)` |
| A checkout fails and the log says `stripe refused create checkout session` | The runtime key lacks **Checkout Sessions**, its own group in the editor | The start line says `the key lacks Checkout Sessions`. Set that group to Write on the key; it takes effect at once |
| The API or the worker does not start, and the deploy rolls back | A key of the wrong mode (a live key in staging, a test key in production), an organization key, or a secret key. The boot check refuses it | `/tadas/<env>/api` and `/tadas/<env>/maintenance`; the refusal names the setting and says why |
| A process refuses to start: `TADAS_STRIPE_ORG_KEY is no longer read` | A line with that name is left in `.env` or the shell | Remove it. The runtime key goes in `TADAS_STRIPE_RUNTIME_KEY`; the bootstrap's in `TADAS_STRIPE_BOOTSTRAP_KEY` |
| Stripe shows failed deliveries answered `400` | The signing secret does not match the endpoint's | Stripe: **Developers** → **Webhooks** → the endpoint → its deliveries. Roll the secret as above |
| Failed deliveries answered `503` | `tadas/<env>/stripe_webhook_secret` is `off` | The same page. Run the bootstrap, then roll the API |
| A plan does not change after a paid checkout | The worker could not apply the delivery | `/tadas/<env>/maintenance`, and the queue `tadas-<env>-webhooks-dead`, where a delivery lands after its retries |
| A call fails with a permission error naming a resource | The key lacks that permission | Add it to the key the call runs under (the tables above). It takes effect at once |
| The bootstrap stops with `set TADAS_STRIPE_BOOTSTRAP_KEY` | The shell holds no bootstrap key. It does not read the runtime key | Export the bootstrap key as in step 5 |

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
- **The runtime key**, `tadas-<env>-runtime`. The secret that held it
  is gone, so a recreated environment needs it written again (step 4).
  If the environment does not come back, delete the key under
  **Developers** → **API keys**.
- **The bootstrap key.** It belongs to the account, not the
  environment, and stays.

## Production (parked)

Production is not running yet. When it is, the steps are the same, with
these differences:

- The account is the live one, `acct_1UIfTS4Dj4HbbS1T`. Make both keys
  there, not in the sandbox: `tadas-production-runtime` and
  `tadas-bootstrap-live`, with the same rows. Each starts with
  `rk_live_`.
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
- **An organization key or a secret key in any environment.** Refused
  the same way. Make a restricted key.
- **The bootstrap key in a secret store or a process.** It stays in the
  shell of the person who runs the bootstrap.
- **A key in the repository, a chat, a ticket, or a log.** The key's
  name is enough everywhere. The value lives in the password manager
  and the secret store only.
