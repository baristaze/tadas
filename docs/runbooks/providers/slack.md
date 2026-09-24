# Slack: operating the Slack app

Tadas is a Slack app that each org installs into its own Slack
workspace. People type `/tadas` in Slack, and Tadas posts reminders and
task updates in the channel the org picks. This page is for a person who
has never opened Slack's app settings: what lives where, what is set by
hand once, what the deploy sets, and what to do when it breaks.

The two other providers have pages of their own:
[Stripe](stripe.md) (billing) and [WorkOS](workos.md) (sign-in).

## How it works, in one screen

```text
Slack                                        Tadas (one environment)
-----                                        -----------------------
app "Tadas (staging)"  A0C3MMXH2AH           API  https://api.staging.tadas.fyi
  /tadas  ------------- signed POST -------> /webhooks/slack/commands  -+
  events  ------------- signed POST -------> /webhooks/slack/events    -+-> queue tadas-staging-slack
  "Allow" on install -- browser redirect --> /webhooks/slack/oauth        |
                                                                          v
workspace T...  <------ chat.postMessage --- maintenance worker <---------+
                        (the org's own token)
```

- Slack calls the API over HTTPS. Each call is signed with the app's
  **signing secret**, and the API checks the signature before it reads
  anything. A call that fails the check is refused with `401`.
- The API answers Slack at once and puts the call on the `slack` queue.
  The worker does the work: it reads tasks, adds one, binds a channel,
  and answers the person through Slack.
- An org installs the app from Tadas's settings. The install is OAuth v2:
  Slack hands Tadas a **bot token for that workspace alone**. Tadas keeps
  it as the org's own secret, never on a row and never in a log, and
  renews it every twelve hours (token rotation).
- One workspace belongs to one org. A second org installing the same
  workspace is refused.

## The levels, and what lives at each

```text
Slack app  (one per Tadas environment)             api.slack.com/apps/<app id>
+-- App Credentials: client id, client secret, signing secret
+-- the manifest: bot user, /tadas, events, redirect URL, scopes, token rotation
+-- distribution: public, so any workspace can install it
|
+-- workspace  (one per org that installed it)
    +-- the bot user @tadas and its token      held by Tadas, per org
    +-- channels                               the org binds one with /tadas connect
```

| Level | What it is | What Tadas keeps there | Who sets it |
|-------|------------|------------------------|-------------|
| App | The Tadas integration for one environment. Its settings are at `api.slack.com/apps/<app id>`. Staging's app is `A0C3MMXH2AH`, in the workspace `TQSHA9YBT`. | Everything below | A person, from the committed manifest |
| Manifest | The app's whole configuration as one JSON document: display name, bot user, the `/tadas` command and its URL, the events URL and the events, the OAuth redirect URL, the bot scopes, Socket Mode off, token rotation on. | `deployment/slack/manifest.<environment>.json` | A person pastes it; the file is the record |
| App Credentials | On **Basic Information**: the **Client ID** (not a secret), the **Client Secret**, and the **Signing Secret**. | The client id in the environment's Terraform root; the two secrets in the environment's secret store | A person, once, and at each rotation |
| Distribution | Whether workspaces other than the app's own may install it. | Public | A person, once per app |
| Workspace | A Slack team that installed the app. It gets a bot user there, `@tadas`, and Tadas gets a bot token for it. | One installation per org, and its token as the org's own secret | The org's owner or admin, from Tadas's settings |
| Channel | Where the org's reminders and task updates go. The bot must be a member. | The channel id on the installation | The org, in Slack: `/invite @tadas`, then `/tadas connect` |

### The bot's scopes, and why each

| Scope | Needed for |
|-------|------------|
| `commands` | The `/tadas` slash command |
| `chat:write` | Posting reminders and task updates in the bound channel, the first line of `/tadas connect`, and the reply to a mention |
| `app_mentions:read` | Receiving `app_mention`, so `@tadas` answers with the usage |
| `users:read` | `users.info`: who typed the command |
| `users:read.email` | The email on that person's profile, which is how Tadas matches them to a member of the org |

Nothing else. The app never asks for `incoming-webhook`,
`channels:read`, `channels:history`, or `chat:write.public`: the channel
is bound by typing a command in it, and the bot posts only where it was
invited.

### The events, and what each does

| Event | Tadas does |
|-------|------------|
| `app_mention` | Answers the usage in the mention's thread, once |
| `app_home_opened` | Publishes the Home tab: the commands and how to bind a channel |
| `app_uninstalled` | Deletes the org's installation and its token |
| `tokens_revoked` | The same, when Slack names the bot's token |

### The commands

| Command | Answers, to the person who typed it alone |
|---------|--------------------------------------------|
| `/tadas` | Your ten newest open tasks: assigned to you, or unassigned and made by you, as My Tasks in Tadas. When there are more, a count and a link to Tadas |
| `/tadas team` | The org's ten newest open tasks, anyone's or nobody's, with the same count and link |
| `/tadas add <title>` | Adds a task, made by you |
| `/tadas connect` | Makes this channel the one Tadas posts to. An owner or an admin types it, after `/invite @tadas` |
| `/tadas help` | The usage; anything else answers it too |

The person is matched by the email on their Slack profile: the member of
the org whose Tadas sign-in holds the same address. Someone Tadas does not
know is told to ask an owner or an admin to invite that address, and to
sign in once with it. Editing and deleting stay in Tadas.

## Which Tadas environment uses which app

A Slack app has one set of request URLs, so each deployed environment has
its own app.

| Tadas environment | Slack app | Manifest | Client id in | Secrets |
|-------------------|-----------|----------|--------------|---------|
| `local` | none: the twin | none | none | none |
| `staging` | `A0C3MMXH2AH`, "Tadas (staging)" | `deployment/slack/manifest.staging.json` | `deployment/terraform/environments/staging/main.tf`, `slack_client_id` | `tadas/staging/slack_client_secret`, `tadas/staging/slack_signing_secret` |
| `production` (parked) | made when production opens, "Tadas" | `deployment/slack/manifest.production.json` | `deployment/terraform/environments/prod/main.tf`, `slack_client_id` | `tadas/production/slack_client_secret`, `tadas/production/slack_signing_secret` |

Each org's bot token is a secret of its own, which the application
writes: `tadas/<env>/app/org/<org id>/slack_bot_<installation id>`. Nobody
writes those by hand.

## First-time setup, by hand

Do these in order. Slack checks the events URL when the manifest is
saved, and the API answers that check only once it holds the signing
secret, so the secrets come before the manifest.

### 1. Merge, and let staging deploy

The deploy makes the two secrets, each holding `off`, runs the migration,
and rolls the API and the worker. With `off`, **Add to Slack** and every
call from Slack answer `503 slack_unavailable`, and the API's log names
`slack=off` at start.

**Check**, under your own sign-in:

```bash
aws secretsmanager describe-secret --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/slack_signing_secret --query '{name: Name, changed: LastChangedDate}'
```

`ResourceNotFoundException` means the deploy has not run yet. Wait for
it. A value written before then makes a secret Terraform does not own,
and the next deploy fails on it.

### 2. Let the tasks write an org's token

An install writes the workspace's token into the org's own secret. The
ceiling on what a task may do is the account's task boundary, the policy
`tadas-task-boundary-staging`. The bootstrap root holds it, and no deploy
can change it. Apply that one policy, as the account's administrator:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sso login --profile tadas-staging-admin
export AWS_PROFILE=tadas-staging-admin
terraform -chdir=deployment/terraform/bootstrap/staging init -input=false -reconfigure \
  -backend-config=bucket=tadas-state-792394000601 \
  -backend-config=key=bootstrap/terraform.tfstate \
  -backend-config=region=us-west-2 -backend-config=use_lockfile=true
terraform -chdir=deployment/terraform/bootstrap/staging apply \
  -target=module.account.aws_iam_policy.task_boundary \
  -var owner_email=<the owner's address>
unset AWS_PROFILE
```

`-target` keeps the apply to the one policy, so nothing else in the root
moves.

**Check.** The plan shows `module.account.aws_iam_policy.task_boundary`
updated in place, and nothing else: the statement `ItsTenantsSecrets`
(create, put, and delete under `tadas/staging/app/org/`) is added.

### 3. Write the two secrets, and commit the client id

Open [api.slack.com/apps/A0C3MMXH2AH](https://api.slack.com/apps/A0C3MMXH2AH)
→ **Basic Information** → **App Credentials**. Three values are there:
**Client ID**, **Client Secret** (click **Show**), and **Signing Secret**
(click **Show**).

Keys exported in the shell outrank a profile, so clear them first.
`read -rs` takes each value without showing it:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sso login --profile tadas-staging
read -rs VALUE    # the Signing Secret
aws secretsmanager put-secret-value --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/slack_signing_secret --secret-string "$VALUE"
read -rs VALUE    # the Client Secret
aws secretsmanager put-secret-value --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/slack_client_secret --secret-string "$VALUE"
unset VALUE
```

The **Client ID** is not a secret. It goes in a pull request, in
`deployment/terraform/environments/staging/main.tf`:

```hcl
  slack_client_id = "<the Client ID>"
```

Its merge deploys staging, and the new tasks start with the two secrets
too. To pick up a secret without a deploy, roll the two services:

```bash
aws ecs update-service --profile tadas-staging --region us-west-2 \
  --cluster tadas-staging --service api --force-new-deployment
aws ecs update-service --profile tadas-staging --region us-west-2 \
  --cluster tadas-staging --service maintenance --force-new-deployment
```

**Check.** `/tadas/staging/api` names `slack=web` in its start line.
Until all three values are in, it names `slack=off`.

### 4. Paste the manifest

Still at [api.slack.com/apps/A0C3MMXH2AH](https://api.slack.com/apps/A0C3MMXH2AH):

1. **App Manifest** (left menu, under Features). Pick the **JSON** tab.
2. Select everything there, and paste the whole of
   `deployment/slack/manifest.staging.json`.
3. **Save Changes**. Slack lists what changes: the name becomes "Tadas
   (staging)", the sample command and shortcut go, `/tadas` arrives, the
   scopes and events change, Socket Mode turns off, token rotation turns
   on. Confirm.
4. Slack sends the events URL a challenge. When staging answers it, the
   page says the URL is **Verified**. If it says the URL did not respond,
   the signing secret is not in the running API yet: finish step 3, then
   open **Event Subscriptions** and click **Retry**.

Token rotation cannot be turned off once it is on. That is the intent.

**Check.** **Event Subscriptions** shows the request URL
`https://api.staging.tadas.fyi/webhooks/slack/events` with a green
**Verified**. **Slash Commands** shows `/tadas` with
`https://api.staging.tadas.fyi/webhooks/slack/commands`. **OAuth &
Permissions** shows the redirect URL
`https://api.staging.tadas.fyi/webhooks/slack/oauth` and the five bot
scopes. **Socket Mode** is off.

### 5. Let any workspace install it

**Basic Information** → **Manage Distribution**. Tick the checklist
(**Remove Hard Coded Information** asks you to confirm the app keeps no
token in code, which is true), then **Activate Public Distribution**.
Without this, only the app's own workspace can install it. Public
distribution does not list the app in the Slack Marketplace; that is a
separate submission, and Tadas does not make it.

### 6. Install from Tadas, and bind a channel

1. Sign in to [app.staging.tadas.fyi](https://app.staging.tadas.fyi) as
   an owner or an admin of an org, and open **Settings**. The **Slack**
   card says "Not installed."
2. Click **Add to Slack**. Slack's page asks to install "Tadas (staging)"
   in a workspace, with the five permissions. Pick the workspace and click
   **Allow**.
3. Slack sends the browser back to the settings page, which says "Tadas
   is in Slack." The card says "Installed in <workspace>. No channel gets
   posts yet."
4. In Slack, in the channel for reminders and task updates, type
   `/invite @tadas`, then `/tadas connect`. Tadas posts a first line
   there, and the card says it is posting to that channel.

**Check.** In Slack, `/tadas help` answers with the usage, `/tadas add
Buy milk` answers "Added", and the task is in Tadas, made by you. Give a
task yesterday's date as its due date: its morning has passed everywhere,
so the reminder arrives in the channel within a minute. If `/tadas` says
you are not a member, the email on your Slack profile is not the address
you sign in to Tadas with.

## What is automated, and by what

| What | Done by | When |
|------|---------|------|
| The two secret containers, holding `off` | Terraform, `deployment/terraform/modules/secrets` | The first deploy that carries them |
| The `slack` queue and its dead-letter queue | Terraform, `deployment/terraform/modules/environment` | Every deploy |
| The client id, the redirect URL, and the portal URL, inside the processes | The deploy: each task's environment | Every task start |
| The two secrets inside the processes | The deploy: each task gets them at start | Every task start |
| The tasks' right to write an org's token | The account module's task boundary (the ceiling, by a person's bootstrap apply) and the secrets module's policy (the grant, every deploy) | Once; every deploy |
| An org's installation and its token | The API, on the install's redirect | Each install |
| The token's renewal | Whichever process uses the token, one hour before it expires | Every twelve hours, on use |
| The app's configuration | Nothing: a person pastes the manifest | Once, and after a change to the manifest |

The manifest in the repository is the record. A change to the app is a
pull request to the manifest, then a paste. A change of scopes also asks
every installed workspace to approve again: an owner or an admin clicks
**Add to Slack again** in Tadas.

## Local development

A laptop has no public URL, so Slack itself never calls it, and Tadas
adds no tunnel. Locally Slack is the twin: `.env.example` sets
`TADAS_SLACK_BACKEND=twin`.

- **Add to Slack** in the local portal installs at once into the twin's
  own workspace, `TTWIN0001` ("Twin Workspace"), with no Slack page in
  between. The settings card shows it installed.
- The worker posts to the twin, which logs each post (`slack twin posted
  twin.000001 to C…`).
- Slack's calls in are exercised by the tests, which sign each request
  with the twin's signing secret exactly as Slack signs, and by a signed
  request to the local API. The twin's secret is `TWIN_SIGNING_SECRET` in
  `integrations/src/tadas/integrations/slack/twin.py`; nothing outside a
  laptop or a test accepts it. A signed `/tadas help`:

```bash
uv run python - <<'EOF'
import urllib.request
from urllib.parse import urlencode
from tadas.integrations.slack.requests import sign
from tadas.integrations.slack.twin import TWIN_SIGNING_SECRET

body = urlencode({"command": "/tadas", "text": "help", "team_id": "TTWIN0001",
                  "channel_id": "C0LOCAL", "user_id": "U0LOCAL", "trigger_id": "local.1",
                  "response_url": "https://hooks.slack.com/commands/local"}).encode()
at, signature = sign(body, TWIN_SIGNING_SECRET)
request = urllib.request.Request("http://127.0.0.1:8000/webhooks/slack/commands", data=body,
                                 headers={"X-Slack-Request-Timestamp": at, "X-Slack-Signature": signature})
print(urllib.request.urlopen(request).status)   # 200; the worker's log shows the answer
EOF
```

To try the real Slack, use staging. Never point a Slack app's URLs at a
laptop.

## Rotation

**The signing secret.** On **Basic Information** → **App Credentials**,
click **Regenerate** beside the Signing Secret. From that moment Slack
signs with the new one, so write it at once (step 3) and roll `api`.
Calls in the minutes between are refused with `401`; Slack retries an
event, and a person types a command again.

**The client secret.** **Regenerate** beside the Client Secret, write it
(step 3), roll `api` and `maintenance`. Until they roll, an install and a
token's renewal fail. A renewal is tried again on the next use, and the
token in hand works for its last hour.

**The client id** never changes for an app.

**An org's bot token** renews itself every twelve hours, and each
refresh token works once. Nothing is done by hand. To end one org's
token at once, the org clicks **Remove from Slack** in Tadas, or removes
the app in Slack; either deletes it.

**A change of scopes or events.** Change the manifest in a pull request,
merge, and paste it (step 4). Each org then clicks **Add to Slack again**
to approve the new scopes; its channel stays.

## When it breaks

| What you see | Why | Where to look |
|--------------|-----|---------------|
| **Add to Slack** says the Slack app's credentials are not configured (`503`) | One of the three values is missing: a secret is still `off`, or `slack_client_id` is empty | `/tadas/<env>/api` names `slack=off` at start. Step 3 |
| `/tadas` answers `dispatch_failed`, or nothing | The API refused or did not answer: the signing secret is wrong or `off`, or the API is down | `/tadas/<env>/api`: `slack_signature_invalid` (`401`) or `slack_unavailable` (`503`) on `/webhooks/slack/commands` |
| Event Subscriptions will not verify the URL | The same, for the events URL | As above, on `/webhooks/slack/events`. Step 3, then **Retry** |
| The settings page says the install link expired or was already used | The state works once and for ten minutes | Click **Add to Slack** again |
| It says the workspace is installed for another Tadas org | One workspace belongs to one org | That org clicks **Remove from Slack**, or pick another workspace |
| It says Slack refused the install | The code exchange failed: a wrong client secret, or a redirect URL the app does not list | `/tadas/<env>/api`: `slack install failed at Slack: <code>`. Step 3; the manifest's redirect URL |
| An install fails with `AccessDeniedException` on `CreateSecret` in the log | The account's task boundary lacks the tenant-secret writes | Step 2 |
| `/tadas` says Tadas is not installed for this Slack workspace | No org installed the app in that workspace, or it was removed | Install from Tadas's settings |
| `/tadas` says you are not a member | Your Slack profile's email is not an address a member of the org signed in with | Ask an owner or an admin to invite that address, then sign in once |
| `/tadas connect` says `@tadas` is not in the channel | The bot was never invited there | `/invite @tadas`, then `/tadas connect` again |
| The card says posting fails, and names the channel | Slack refused the channel for good: archived, deleted, or the bot was removed | `/tadas connect` in a working channel |
| The card says Slack no longer accepts the install's token | A renewal was refused: the app was removed from the workspace, or the token revoked | **Add to Slack again** |
| Reminders do not arrive, and nothing fails | No channel is bound, or the installation is broken; the worker drops the post and says why | `/tadas/<env>/maintenance`: `slack post <id> dropped: …` |
| Posts are late | Slack rate limited the bot. The worker parks the post for as long as Slack asked and tries again | `/tadas/<env>/maintenance`, and the worker's outcome counter |
| A command is received but never answered | The worker failed on it; after its retries it lands in `tadas-<env>-slack-dead` | `/tadas/<env>/maintenance`, and the queue's depth |
| `@tadas` does not answer | The manifest's `app_mention` event or `app_mentions:read` scope is missing, or the org has not approved the new scope | The App Manifest page; **Add to Slack again** |

## When an environment is torn down

`scripts/cloud_nuke.sh` deletes the environment's two Slack secrets with
everything else, and the installations go with the database. The Slack
app stays, with its URLs pointing at an API that no longer answers:
`/tadas` fails in every workspace that installed it until a new staging
answers. The workspaces keep the app installed until someone removes it
in Slack. Each org's bot token stays in Secrets Manager under
`tadas/<env>/app/org/`: the application wrote it, so Terraform does not
own it, and the nuke only counts them. If the environment is not coming
back, delete them:

```bash
aws secretsmanager list-secrets --profile tadas-staging-admin --region us-west-2 \
  --filters Key=name,Values=tadas/staging/app/org/ --query 'SecretList[].Name' --output text \
  | tr '\t' '\n' | while read -r name; do
      aws secretsmanager delete-secret --profile tadas-staging-admin --region us-west-2 \
        --secret-id "$name" --force-delete-without-recovery
    done
```
 A recreated staging needs steps 1 to 3 again (the client id is
already committed), and each org installs again from its settings. The
manifest needs no paste unless it changed.

## Production (parked)

Production is not running yet. When it opens:

1. Make its app: [api.slack.com/apps](https://api.slack.com/apps) →
   **Create New App** → **From a manifest**. Pick the workspace that will
   own the app, pick **JSON**, paste
   `deployment/slack/manifest.production.json`, and create. Slack checks
   the events URL at once; it fails until step 3, which is expected.
2. Steps 1 and 2 above, for production, under `tadas-prod-power` and only
   when that change is explicitly authorized. `tadas-prod` only reads.
3. Step 3 with production's names: `tadas/production/slack_signing_secret`,
   `tadas/production/slack_client_secret`, and `slack_client_id` in
   `deployment/terraform/environments/prod/main.tf`. Then **Event
   Subscriptions** → **Retry**, and the URL turns verified.
4. Step 5, then install from production's settings.

Never put a secret or a token in the repository, a chat, a ticket, or a
log. The names are enough everywhere.
