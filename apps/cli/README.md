# Tadas CLI

Tadas from the terminal. A command does one thing and returns; `listen`
stays and prints every change in the org as it happens.

```bash
uv run tadas login --org ajax        # confirm the code in the browser
uv run tadas login --dev-email bob@example.test --org ajax   # local stack only
uv run tadas whoami
uv run tadas orgs                    # * marks the session's org
uv run tadas switch fabrikam         # the old session ends
uv run tadas upload spec.pdf         # --type, --json
uv run tadas listen                  # who did what to which record
uv run tadas logout
```

## Conventions

- A dumb client: every command calls the API through `tadas.client` and
  shows the answer. A refusal prints the API's code, message, and request id.
- Exit codes: 0 done, 1 the API refused, 2 usage, 3 not signed in, 4 the
  API is unreachable. A setting the environment got wrong is usage.
- The session lives in `$TADAS_HOME/session.json` (default `~/.config/tadas`,
  mode 600) and goes only to the API that issued it. `TADAS_TOKEN` wins over
  it. `TADAS_API_URL` or `--api` names the API. `TADAS_HTTP_TIMEOUT_SECONDS`,
  `TADAS_HTTP_RETRIES`, and `TADAS_HTTP_RETRY_BACKOFF_SECONDS` tune the client.

## Test

```bash
uv run pytest -q apps/cli/tests
```
