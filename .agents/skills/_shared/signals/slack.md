# Signals: slack

The org's Slack app: its install, the posts to the channel the org
bound, and the calls Slack makes (`/tadas`, a mention, the App Home, an
uninstall), which the API checks and queues and the worker handles.

## Kinds

- `SLACK_POST`: one line to the org's channel (a task created,
  completed, or reminded of), recorded under the item's key so a rerun
  posts nothing. It parks on Slack's rate limit for the time Slack
  named, and marks the installation broken when Slack refuses the
  channel or the token for good. One that failed for good is a line the
  channel never got.

## Outcomes

- `slack_inbound`: `queued`, a call the API checked and queued; then
  the worker's `handled`; `refused`, an answer no retry changes, said in
  the log, and the call is done; `failed`, which stays on the queue and
  comes back; `malformed`; and `receive_error`, the queue could not be
  read.
- `slack_install`: one per install that came back from Slack:
  `installed`, `cancelled` (the person cancelled on Slack's page),
  `expired`, `taken` (the workspace is another org's), or `failed`.

## Queues

- `tadas-<env>-slack`: the calls from Slack the API checked at
  `/webhooks/slack/commands` and `/webhooks/slack/events` and queued.
  They come in through `/tadas/<env>/api`, and their handling is in
  `/tadas/<env>/maintenance`. A message in `tadas-<env>-slack-dead` is a
  call the worker could not handle after its retries.

## Log lines

Each line names the secret it points to; the secret's value is never
read.

- `slack=off` on a start line, a `503` (`slack_unavailable`) on
  `/v1/slack/installation` or `/webhooks/slack/*` in the access lines
  of `/tadas/<env>/api`, or `slack post <id> dropped: no Slack app is
  configured` in `/tadas/<env>/maintenance`: Slack is unconfigured, so
  "Add to Slack" and `/tadas` answer nothing and posts go nowhere.
  `tadas/<env>/slack_client_secret` or `tadas/<env>/slack_signing_secret`
  is `off`, or `slack_client_id` is empty in the environment root.
  `slack=web` is the healthy start line, and a laptop runs Slack's twin
  on purpose (`slack=twin`), which is not a finding.
- A `401` (`slack_signature_invalid`) on `/webhooks/slack/*` in the
  access lines of `/tadas/<env>/api`: the signing secret does not match
  the app's, so every command and event is refused.
- `slack install failed at Slack: <code>` in `/tadas/<env>/api`: an
  install the app's client id or client secret could not finish.
  `slack install could not keep its token` there is the token's store
  not answering; the person installs again.
- `slack token of org <id> is revoked` or `slack channel of org <id> is
  unusable` at `WARNING` in `/tadas/<env>/maintenance`: one org's
  installation is broken, not the environment's. The org installs
  again, or types `/tadas connect` in a channel the app is in; not a
  finding about a secret.
- `slack inbound: <key> failed; the queue hands it back` at `ERROR` in
  `/tadas/<env>/maintenance`: one call the worker could not handle,
  with the exception under it, left on the queue to come back.

A finding about a secret names the secret and
`docs/runbooks/providers/slack.md`.

## Search

`slack=|webhooks\/slack\/[a-z]+ (401|503)|v1\/slack\/installation 503|no Slack app is configured|slack token of org|slack channel of org|slack install`

## Report

Locally, where a laptop runs Slack's twin by design, the first line is
`- Slack: the twin`, and it names no secret. Otherwise:

```markdown
- Slack: <configured | off: tadas/<env>/slack_client_secret, tadas/<env>/slack_signing_secret, slack_client_id | signature refused: tadas/<env>/slack_signing_secret | not in the window>, broken installations <org ids, or none>
- Slack calls: queue slack <n> (dead <n>), <slack_inbound outcomes>; installs <slack_install outcomes>
```
