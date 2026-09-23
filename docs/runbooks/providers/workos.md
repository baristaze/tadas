# WorkOS: operating the sign-in

People sign in to Tadas through WorkOS AuthKit: an email code or link,
Google, GitHub, or their team's own single sign-on. WorkOS proves who
the person is. Everything after that (the person, their orgs, their
sessions) is Tadas's own. This page is for a person who has never opened
the WorkOS dashboard: what lives where, what is set by hand once, what a
command checks, and what to do when it breaks.

The two other providers have pages of their own:
[Stripe](stripe.md) (billing) and [Slack](slack.md).

## The levels, and what lives at each

WorkOS nests these levels. Every Tadas setting sits on exactly one.

```text
WorkOS team                                          the people who may open the dashboard
|
+-- environment  Staging                             serves local and staging
|   +-- API keys                                     the environment's secret key
|   +-- the environment's own client id              not used by Tadas
|   +-- the environment's Redirects page             not read for Tadas's sign-in
|   +-- authentication methods                       email code or link, Google, GitHub
|   +-- application  "Tadas App"  client_01M3640D8WBF9KC0P89YW4E72N
|   |   +-- Redirects tab                            redirect URIs, the login initiation URI
|   +-- organizations                                one per Tadas team org, external_id = the org's id
|   |   +-- single sign-on, verified domains         set up by the org's admin
|   +-- users and invitations                        made by sign-ins and by Tadas
|
+-- environment  Production                          serves production alone
    +-- the same, with application client_01M363XVP5FGF2P45FHK9B7MJD
```

| Level | What it is | What Tadas keeps there | Who sets it |
|-------|------------|------------------------|-------------|
| Team | The WorkOS account. It holds the people who may use the dashboard. | Two environments | A person, once |
| Environment | A world of its own: its own keys, users, and organizations. Staging and Production share nothing. | Everything below | WorkOS makes both |
| API key | The environment's secret key. Tadas's API uses it for the management calls: organizations, invitations, the Admin Portal link. | One per environment, in the secret store | A person, once per environment |
| Application | An AuthKit application, the "Tadas App". Its **client id** is what every sign-in URL carries. It is not a secret. An environment also has a client id of its own; Tadas does not use that one. | The client id is committed in `deployment/workos/environments.yaml`, in each Terraform root (`workos_client_id`), and in `.env.example` for local | A person makes the application, once per environment |
| The application's Redirects tab | Where AuthKit may send a person back to (the **redirect URIs**), and where it sends a person whose sign-in did not start at Tadas (the **login initiation URI**). | The portal's `/auth/callback` and `/login` | A person, by hand: no API writes it |
| The environment's Redirects page | A list at the environment level. AuthKit does not read it for an application. | Nothing | Nobody |
| Authentication methods | Which ways to sign in AuthKit offers. | Email, Google, GitHub | A person, once per environment |
| Organizations | One WorkOS organization per Tadas team org, carrying the Tadas org's id as its `external_id`. Made the first time an owner or an admin invites someone or opens single sign-on. | Made by the API | Tadas |
| Admin Portal | WorkOS's own pages where an org's admin connects their company's identity provider and verifies a domain. Tadas opens it with a link it asks the API for. | Nothing to set | The org's admin, from Tadas's settings page |

## Which Tadas environment uses which WorkOS environment

| Tadas environment | WorkOS environment | Application client id | Its redirect URIs | Login initiation URI |
|-------------------|--------------------|-----------------------|-------------------|----------------------|
| `local` | Staging | `client_01M3640D8WBF9KC0P89YW4E72N` | `http://localhost:55173/auth/callback` (the stack's portal), `http://localhost:5173/auth/callback` (the Vite dev server) | none needed |
| `staging` | Staging | `client_01M3640D8WBF9KC0P89YW4E72N` | `https://app.staging.tadas.fyi/auth/callback` | `https://app.staging.tadas.fyi/login` |
| `production` | Production | `client_01M363XVP5FGF2P45FHK9B7MJD` | `https://app.tadas.fyi/auth/callback` | `https://app.tadas.fyi/login` |

Local and staging share one WorkOS environment and one application. So
the application's Redirects tab holds the three staging-side URIs. Each
Tadas environment still takes only its own callback: the API refuses a
sign-in that asks to come back anywhere else
(`TADAS_SIGN_IN_REDIRECT_URIS`).

Sharing has one consequence: the WorkOS organizations and users that
local runs make sit in the same Staging environment as staging's.
Neither sees the other's, because Tadas finds an organization by the
Tadas org's id.

## First-time setup, by hand

Do these once per WorkOS environment. Staging first.

### 1. Make the application

1. Sign in at [dashboard.workos.com](https://dashboard.workos.com).
2. Pick the environment in the switcher (top left): **Staging**.
3. Open **Applications**. If the "Tadas App" is there, open it.
   Otherwise create an AuthKit application named "Tadas App".
4. Copy its **client id**. It must be the one the table above names.

**Check.** The client id matches `deployment/workos/environments.yaml`.
If WorkOS made a new application with a new id, the committed id is
wrong: change it in that file, in the environment's Terraform root, and
in `.env.example`, in one pull request.

### 2. Add the redirects on the application's Redirects tab

No API writes an application's redirects, so this step is by hand.

1. In the application, open the **Redirects** tab.
2. Add each redirect URI the table above names for this WorkOS
   environment. For Staging that is three.
3. Set the **login initiation URI** to the portal's `/login`
   (`https://app.staging.tadas.fyi/login` for Staging).
4. Save.

Do not add them on the environment's own Redirects page. AuthKit does
not read that page for an application, so an entry there changes
nothing.

**Check** with the bootstrap (see below). It asks AuthKit about each
URI and says `present` or `missing`.

### 3. Turn on the ways to sign in

1. In the environment, open **Authentication**.
2. Turn on email (a one-time code or a magic link), Google, and
   GitHub.

In Staging, WorkOS can use its own demo credentials for Google and
GitHub, so nothing more is needed. In Production, each needs an OAuth
app of your own at Google and at GitHub, and its credentials entered
here.

### 4. Make the API key

1. In the environment, open **API Keys**.
2. Create a secret key. Name it after the Tadas environment, for
   example `tadas-staging`. WorkOS shows it once. Keep it in your
   password manager.

The key is the environment's, not the application's. Local and staging
each get a key of their own from the same Staging environment, so one
can be revoked without the other.

### 5. Let the first deploy make the secret container

The first deploy that carries sign-in makes
`tadas/<env>/workos_api_key` in the environment's AWS account, holding
`off`. With `off`, the API starts, says so in its log, and every sign-in
through WorkOS answers `503`.

**Check**, under your own sign-in:

```bash
aws secretsmanager describe-secret --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/workos_api_key --query '{name: Name, changed: LastChangedDate}'
```

`ResourceNotFoundException` means the deploy has not run yet. Wait for
it. A value written before then makes a secret Terraform does not own,
and the next deploy fails on it.

### 6. Write the key into the secret store

Keys exported in the shell outrank a profile, so clear them first.
`read -rs` takes the value without showing it:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sso login --profile tadas-staging
read -rs VALUE    # paste the key, press Enter; nothing is shown
aws secretsmanager put-secret-value --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/workos_api_key --secret-string "$VALUE"
unset VALUE
```

### 7. Let the API pick it up

The API reads the key when a task starts. The next deploy does it. To
pick it up now:

```bash
aws ecs update-service --profile tadas-staging --region us-west-2 \
  --cluster tadas-staging --service api --force-new-deployment
```

**Check.** The API's start line in `/tadas/staging/api` names the
provider as `WorkOS (https://api.workos.com, client
client_01M3640D8WBF9KC0P89YW4E72N)`. Before the key, it names `none`
and a warning says every sign-in answers `503`. Then open
`https://app.staging.tadas.fyi`, choose to sign in, and finish with an
email code. You land in Tadas, signed in.

## What is automated, and by what

| What | Done by | When |
|------|---------|------|
| The secret container, holding `off` | Terraform, `deployment/terraform/modules/secrets` | The first deploy that carries it |
| The key inside the API | The deploy: each API task gets it at start | Every task start |
| The client id and the allowed callback | Terraform, from the environment's root | Every deploy |
| The check that every redirect is accepted | `tadas-ops workos-bootstrap` | A person runs it after a change to the Redirects tab or to `environments.yaml` |
| Organizations, invitations, Admin Portal links | The API | When an owner or an admin invites or opens single sign-on |

### The bootstrap

`tadas-ops workos-bootstrap` reads `deployment/workos/environments.yaml`
and asks AuthKit, for each redirect URI, whether it accepts it for the
application. It does this with the same request a browser makes to
start a sign-in, and reads where AuthKit sends it. That answer is the
truth; the dashboard is where it is changed.

For an application, the command only checks. It never writes. A
missing redirect is named, with the dashboard step that adds it, and
the run exits 1. The login initiation URI has no API at all, so the
command prints it as a check to make by eye on the same tab.

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
read -rs WORKOS_API_KEY && export WORKOS_API_KEY    # the Staging environment's key
uv run tadas-ops workos-bootstrap --environment staging
unset WORKOS_API_KEY
```

When every redirect is on the tab, the output ends:

```text
redirect https://app.staging.tadas.fyi/auth/callback: present
login initiation URI: https://app.staging.tadas.fyi/login (check it on the application's Redirects tab; no API reads or writes it)
webhooks: none
nothing to change
```

A second run says `nothing to change` again. `--apply` changes nothing
for an application, since there is nothing the API may write.

The command also lists the environment's own redirect list, and says
AuthKit does not read it. Staging's list holds a stray
`http://localhost:5173/auth/callback`. It is harmless. Delete it by
hand on the environment's Redirects page if you like; the application's
tab keeps its own entry for the same URI, which is the one that counts.

For production the variable is `WORKOS_PRODUCTION_API_KEY`, and the
flag `--environment production`.

## Local development

The laptop signs in through the Staging application, whose Redirects
tab holds the local callbacks.

```bash
read -rs TADAS_WORKOS_API_KEY && export TADAS_WORKOS_API_KEY    # a Staging key
make up
```

`.env.example` names the client id and leaves `TADAS_WORKOS_API_KEY`
commented out on purpose. The Makefile includes that file, and a line
there with an empty value would override what the shell exported.

Without the key, the stack still runs. Sign-in through WorkOS answers
`503`, and the local sign-in by address (`/login/dev`) still works.

## Rotation

1. Make a new API key in the environment (step 4).
2. Write it (step 6).
3. Roll the API (step 7), and check the start line.
4. Revoke the old key under **API Keys**.

Both keys work until the last step, so nobody is signed out. A sign-in
never uses the key anyway: the code exchange uses a one-time verifier
the browser keeps, not a secret. Sessions Tadas already issued are
Tadas's own and outlive any key.

## When it breaks

| What you see | Why | Where to look |
|--------------|-----|---------------|
| Every sign-in through WorkOS answers `503` | `tadas/<env>/workos_api_key` is `off`, or the task started before it was written | `/tadas/<env>/api`: the start line names `identity provider: none (TADAS_WORKOS_API_KEY is not set)`, and a warning follows |
| AuthKit shows an "invalid redirect URI" page | The callback is not on the application's Redirects tab | Run the bootstrap; add what it names on the tab |
| A sign-in that did not start at Tadas lands on a WorkOS error page | The login initiation URI is missing or wrong | The application's Redirects tab |
| An invitation or the Admin Portal link fails | WorkOS is down, or the key was revoked or belongs to the other environment | `/tadas/<env>/api`, then WorkOS's status page |
| A person signs in at WorkOS but Tadas refuses them | Their address is not verified at WorkOS, or single sign-on is not theirs to join (their domain is not verified by the org) | `/tadas/<env>/api`, by the request id the portal shows |

## When an environment is torn down

`scripts/cloud_nuke.sh` does not touch WorkOS. What stays:

- **The organizations** staging's team orgs made, each with the old
  Tadas org's id as its `external_id`. A recreated staging makes new
  orgs with new ids, so the old ones are never found again. They are
  harmless. Delete them under **Organizations** if you want a tidy
  environment; local runs make organizations in the same place, so
  check the `external_id` before you delete.
- **The users** who signed in. Harmless for the same reason.
- **The application and its redirects.** Keep them: the next staging
  uses the same names.
- **The API key.** The secret that held it is gone, so a recreated
  environment needs it written again (step 6). Revoke the old one if
  it is not coming back.

## Production (parked)

Production is not running yet. When it is, the steps are the same, in
the **Production** WorkOS environment, with application
`client_01M363XVP5FGF2P45FHK9B7MJD`:

- Its Redirects tab holds one redirect URI,
  `https://app.tadas.fyi/auth/callback`, and the login initiation URI
  `https://app.tadas.fyi/login`. Never a `localhost` one.
- Google and GitHub need your own OAuth credentials (step 3).
- The everyday production profile, `tadas-prod`, only reads. Writing
  the secret and rolling the API need `tadas-prod-power`, and only when
  that change is explicitly authorized.
- The bootstrap reads `WORKOS_PRODUCTION_API_KEY`:

  ```bash
  read -rs WORKOS_PRODUCTION_API_KEY && export WORKOS_PRODUCTION_API_KEY
  uv run tadas-ops workos-bootstrap --environment production
  unset WORKOS_PRODUCTION_API_KEY
  ```

What must never happen:

- **A Staging key in production, or a Production key in staging or on
  a laptop.** Each WorkOS environment's users and organizations are its
  own. A crossed key makes the management calls reach the other
  environment's organizations, or fail.
- **A key in the repository, a chat, a ticket, or a log.** The names
  are enough everywhere.
