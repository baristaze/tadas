# Integrations

The third-party providers Tadas talks to. Each is one interface with a
real client and a deterministic twin, and a caller never knows which it
holds. Nothing here imports the object model; a provider's errors root
at infra's exception family, since a provider is a dependency the way a
backend is.

## Slack

`tadas.integrations.slack.SlackInterface` posts a message, replies in a
thread, answers a slash command through the `response_url` Slack sent
with it, and publishes the App Home. Its errors are the decisions a
caller needs, not Slack's whole vocabulary:

| Error | Means | What the worker does |
|-------|-------|----------------------|
| `SlackRateLimited` | Slack asked to wait (429), `retry_after` says how long | Parks the item for that long |
| `SlackChannelUnusable` | `channel_not_found`, `not_in_channel`, `is_archived` | Marks the connection broken |
| `SlackNotConfigured` | This process holds no bot token | Posts nothing, says so in the log |
| `SlackFailed` | Anything else, a transport failure included | Fails the item, which retries |

Three impls:

- `SlackWebImpl`, the real client: the Web API with the bot token,
  over one aiohttp session opened at start, every call under
  `TADAS_SLACK_TIMEOUT_SECONDS`. A reply goes only to a URL under
  `https://hooks.slack.com/`.
- `SlackTwinImpl`, the twin: records every call in memory, fails on
  request so a test can drive the rate limit and the unusable channel,
  and stamps each message `twin.<n>` so a record says where it came
  from. It refuses to run outside `local` and `test`.
- `SlackOffImpl`: what a deployed process holds with no bot token. It
  posts nothing and says why.

The worker picks one at boot: the real client when a bot token is set,
the twin in a local process without one, and the off impl otherwise.
Tests never reach Slack.
