# Slack: operating the Slack app

An org connects one Slack channel to Tadas. Tadas posts reminders there,
and people type `/tadas add`, `/tadas list`, and `/tadas help` in it.
All of it runs through one Slack app. This page is for a person who has
never opened Slack's app settings: what lives where, what is set by
hand once, what the deploy sets, and what to do when it breaks.

The two other providers have pages of their own:
[Stripe](stripe.md) (billing) and [WorkOS](workos.md) (sign-in).

## The levels, and what lives at each

```text
Slack workspace                                   where the app is installed, and where the channels are
|
+-- app  "Tadas"  A0C3MMXH2AH                     one app for every Tadas environment
    +-- Socket Mode: on                           Slack sends commands and events over a socket the app opens
    +-- app-level token (xapp-)                   scope connections:write; opens that socket
    +-- bot token (xoxb-)                         the bot's scopes; posts messages and the App Home
    +-- slash command  /tadas
    +-- event subscriptions                       app_mention, app_home_opened
    +-- App Home: the Home tab
```

| Level | What it is | What Tadas keeps there | Who sets it |
|-------|------------|------------------------|-------------|
| Workspace | A Slack team. An app is installed into it, and gets a bot user there, `@tadas`. | The installed app | A person, once |
| App | The Tadas integration, settings at [api.slack.com/apps/A0C3MMXH2AH](https://api.slack.com/apps/A0C3MMXH2AH). | Everything below | A person, once |
| Socket Mode | Slack sends commands and events down a websocket the app opens, instead of posting to a public URL. So nothing in Tadas has to be reachable from the internet for Slack. | On | A person, once |
| App-level token | Opens the Socket Mode connection. Starts with `xapp-`. Scope: `connections:write`. | In `tadas/<env>/slack_app_token` | A person, once |
| Bot token and its scopes | Posts messages and publishes the App Home. Starts with `xoxb-`. What it may do is its **scopes**. A change of scopes takes effect only after the app is **reinstalled** to the workspace. | In `tadas/<env>/slack_bot_token` | A person, once, and after each scope change |
| Slash command | `/tadas`. With Socket Mode it needs no request URL. | One command | A person, once |
| Event subscriptions | Which events Slack sends: `app_mention` (someone writes `@tadas`), `app_home_opened` (someone opens the app's Home tab). | Two bot events | A person, once |
| App Home | The app's own page in Slack. Tadas publishes a short guide there. | The Home tab on | A person, once |
| Channel | Where an org's posts go. The bot must be a member: someone types `/invite @tadas` in it. | Nothing; each org's admin connects its own | The org, from Tadas's settings page |

### The bot's scopes

| Scope | Needed for |
|-------|------------|
| `chat:write` | Posting reminders, and replying in a thread to a mention |
| `commands` | The `/tadas` slash command |
| `app_mentions:read` | Receiving `app_mention`, so `@tadas` answers with the usage |
| `channels:read` | Optional. Lets a person or a check list the channels the bot is in (`users.conversations`), so a post can be verified against a real channel. No code path needs it. |

The app also holds `channels:history` today. No code reads a channel's
history, so it can go at the next scope change.

## Which Tadas environment uses which app

There is **one app, in one workspace, for every environment**. That has
one consequence that decides the rest: Slack spreads its deliveries
across every open Socket Mode connection of the app. Two connections
open means each gets about half of the commands, and a command that
reaches the wrong environment is answered there, or not at all.

So exactly one connection is open at a time, and staging holds it.

| Tadas environment | Bot token | App token | So |
|-------------------|-----------|-----------|----|
| `local` | optional, from the shell | **empty** | Posts through the twin without a bot token, or to Slack with one. Holds no connection. |
| `staging` | `tadas/staging/slack_bot_token` | `tadas/staging/slack_app_token` | Posts, and holds the one connection: every `/tadas` command arrives here |
| `production` (parked) | `tadas/production/slack_bot_token` | `off` while staging holds the connection | See Production below |

In the cloud, the connection is held by the `slack` service
(`tadas-maintenance slack`): exactly one task, never two, not even
during a rollout. It acknowledges each delivery and puts it on the
`slack` queue. The worker (`maintenance`) takes it from there and
posts.

## First-time setup, by hand

### 1. Configure the app

At [api.slack.com/apps/A0C3MMXH2AH](https://api.slack.com/apps/A0C3MMXH2AH):

1. **Socket Mode**: turn it on.
2. **Basic Information** → **App-Level Tokens** → **Generate Token and
   Scopes**. Name it `socket`, add the scope `connections:write`, and
   generate. Copy the `xapp-` token into your password manager.
3. **Slash Commands** → **Create New Command**. Command `/tadas`, short
   description "Add and list your tasks", usage hint
   `add <title> | list | link <code> | help`. Socket Mode asks for no
   request URL.
4. **Event Subscriptions**: turn it on. Under **Subscribe to bot
   events**, add `app_mention` and `app_home_opened`. Save.
5. **App Home**: under **Show Tabs**, turn on the **Home Tab**.
6. **OAuth & Permissions** → **Scopes** → **Bot Token Scopes**: add
   `chat:write`, `commands`, and `app_mentions:read`. Add
   `channels:read` too if you want to check posts against a real
   channel.
7. **Install to Workspace** (or **Reinstall to Workspace**, after any
   change of scopes or events). Approve. Copy the **Bot User OAuth
   Token** (`xoxb-`) into your password manager.

**Check.** In Slack, the app appears under **Apps**. Its Home tab opens.
`/tadas` shows up when you type it in a channel. It answers only once a
Tadas environment holds the connection (step 4).

### 2. Let the first deploy make the secret containers

The first deploy that carries Slack makes two secrets in the
environment's AWS account, each holding `off`:

- `tadas/<env>/slack_bot_token`, injected into the `maintenance`
  service
- `tadas/<env>/slack_app_token`, injected into the `slack` service

With `off`, the worker posts nothing and the bridge holds no
connection. Both say so in their logs.

**Check**, under your own sign-in:

```bash
aws secretsmanager describe-secret --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/slack_app_token --query '{name: Name, changed: LastChangedDate}'
```

`ResourceNotFoundException` means the deploy has not run yet. Wait for
it. A value written before then makes a secret Terraform does not own,
and the next deploy fails on it.

### 3. Write the two tokens

Keys exported in the shell outrank a profile, so clear them first.
`read -rs` takes each value without showing it:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sso login --profile tadas-staging
read -rs VALUE    # the xoxb- bot token
aws secretsmanager put-secret-value --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/slack_bot_token --secret-string "$VALUE"
read -rs VALUE    # the xapp- app-level token
aws secretsmanager put-secret-value --profile tadas-staging --region us-west-2 \
  --secret-id tadas/staging/slack_app_token --secret-string "$VALUE"
unset VALUE
```

### 4. Let the services pick them up

A task reads its secrets when it starts. The next deploy does it. To
pick them up now:

```bash
aws ecs update-service --profile tadas-staging --region us-west-2 \
  --cluster tadas-staging --service maintenance --force-new-deployment
aws ecs update-service --profile tadas-staging --region us-west-2 \
  --cluster tadas-staging --service slack --force-new-deployment
```

The `slack` service stops its old task before it starts the new one, so
there are a few seconds with no connection. Slack retries what it could
not deliver.

**Check.** `/tadas/staging/slack` logs `slack socket mode connection is
open`. In a Slack channel, `/tadas help` answers. For a post, connect a
channel to an org from Tadas's settings page, `/invite @tadas` in it,
and give a task a due time a minute away: the reminder arrives.

## What is automated, and by what

| What | Done by | When |
|------|---------|------|
| The two secret containers, holding `off` | Terraform, `deployment/terraform/modules/secrets` | The first deploy that carries them |
| The `slack` service, one task, and the `slack` queue with its dead-letter queue | Terraform, `deployment/terraform/modules/environment` | Every deploy |
| The tokens inside the processes | The deploy: each task gets them at start | Every task start |
| The app's settings, scopes, command, events, and install | Nothing: Slack's app settings, by hand | Once, and after a change |

No command reconciles the Slack app. Its settings are few and change
rarely, and this page is their record.

## Local development

Local leaves the app token **empty**. A laptop that opens a connection
takes about half of staging's commands, and answers them against the
laptop's database. `.env.example` leaves both Slack tokens commented
out, so the Makefile's include does not blank a value exported in the
shell.

- **Without a bot token**, the local worker posts through the twin. The
  twin records each post in memory and stamps it `twin.<n>`. This is the
  normal way to work.
- **With a bot token** exported (`TADAS_SLACK_BOT_TOKEN`), the local
  worker posts to Slack for real. Posting opens no connection, so it
  does not disturb staging.
- **To drive `/tadas` against a laptop**, the laptop must hold the only
  connection, and staging must hold none. That is a change to staging,
  not a local step, so it is not done casually. Try commands on staging
  instead; the unit tests cover their handling on the laptop.

## Rotation

**The bot token.** An install has one bot token, so there is no
second one to overlap with. A reinstall keeps the same token. To
replace it: revoke it under **OAuth & Permissions** → **Revoke
Tokens**, reinstall the app, copy the new `xoxb-` token, write it (step
3), and roll `maintenance` (step 4). Posts in the minutes between fail
and are retried.

**The app-level token.** Generate a second one under **Basic
Information** → **App-Level Tokens**, write it (step 3), roll `slack`
(step 4), check the log line, then revoke the old one. The two overlap,
so nothing is dropped.

**A change of scopes or events.** Change it in the app's settings,
then **Reinstall to Workspace**. The bot token stays the same, so
nothing needs writing. Check that the new scope works.

## When it breaks

| What you see | Why | Where to look |
|--------------|-----|---------------|
| `/tadas` answers with an error such as `dispatch_failed`, or nothing | No connection is open: `tadas/<env>/slack_app_token` is `off`, or the `slack` task is not running | `/tadas/<env>/slack`: `no Slack app token is set; the Socket Mode connection stays closed`, or no `connection is open` line |
| `/tadas` answers from the wrong data, or only some of the time | Two connections are open: a laptop, or a second environment, holds the app token too | Stop the other one. Only staging holds it |
| Reminders do not arrive, and nothing fails | `tadas/<env>/slack_bot_token` is `off`: the worker drops each post and says why | `/tadas/<env>/maintenance`: `slack post <id> dropped: no bot token is configured` |
| An org's connection shows as broken | Slack refused the channel for good: the channel was archived or deleted, or the bot is not a member | The org re-invites the bot (`/invite @tadas`) or connects another channel |
| Posts are late | Slack rate limited the bot. The worker parks the post for as long as Slack asked and tries again | `/tadas/<env>/maintenance`, and the outcome counter for the worker |
| A command is received but never handled | The worker failed on it; after its retries it lands in `tadas-<env>-slack-dead` | `/tadas/<env>/maintenance`, and the queue's depth |
| `@tadas` does not answer | The app lacks `app_mentions:read` or the `app_mention` event, or was not reinstalled after they were added | The app's settings; reinstall |

## When an environment is torn down

`scripts/cloud_nuke.sh` does not touch Slack. The `slack` service goes
with the environment, so the connection closes and `/tadas` stops
answering until a new staging holds it. The app, its tokens, and the
channels the bot was invited to stay. A recreated staging needs the two
tokens written again (step 3). The channels stay connected to orgs that
no longer exist; a new staging's orgs connect their own.

## Production (parked)

Production is not running yet. The app is one for every environment,
and staging holds the connection. So production, as things stand, holds
the bot token and posts, and leaves `tadas/production/slack_app_token`
at `off`: its people's `/tadas` commands would reach staging.

That is not good enough for real customers. Before production is
opened, make a second app for production, in the workspace production's
customers use, and give production that app's two tokens. Then each
environment holds its own app's one connection. Until that is decided:

- Never write an app token into production while staging holds one.
- Write production's secrets under `tadas-prod-power`, and only when
  that change is explicitly authorized. `tadas-prod` only reads.
- Never put a token in the repository, a chat, a ticket, or a log. The
  names are enough everywhere.
