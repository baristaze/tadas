# Tadas CLI

The product from the terminal, in two modes. Command mode does one thing
and returns: `add`, `ls`, `edit`, `done`, `reopen`, `rm`, `mv`. Realtime
mode stays: `listen` prints every change the team makes as it happens, one
line each, over the same channel the portal uses.

```bash
uv run tadas login --email bob@example.test   # prompts for the password; --org <slug> when you belong to several
uv run tadas orgs                             # the orgs you belong to; * marks the session's
uv run tadas switch beta                      # move the session to another org; the old one ends
uv run tadas add "Migrate DB" --assignee me
uv run tadas ls                               # open tasks; --done, --mine, --json
uv run tadas done 8b949fce                    # the short id `ls` shows
uv run tadas listen                           # the team's tasks; --mine for yours
```

## Conventions

- Dumb client. The CLI never decides; it calls the API through the one
  Python client (`clients/python/`, `tadas.client`) and shows the answer.
  A refusal is printed as the API's own code and message, with the
  request id. A plan's bound is said in its own words, with who lifts it:
  an owner or an admin, in the portal, under Settings, Billing.
- One command, one call, one exit code: 0 done, 1 the API refused, 2
  usage, 3 not signed in, 4 the API is unreachable (any failure of the
  wire: refused, timed out, reset; the API did not decide). A setting the
  environment got wrong is usage too: one line naming the variable and
  exit 2, never a traceback.
- A creating call (`add`) carries an idempotency key, minted by the client.
- The retry is the client's, and the CLI adds none of its own: it passes the
  count and the first delay from its settings the way it passes the timeout.
  Only a failure that can differ on a second attempt goes again, and only on
  a call the API may see twice: a read, and a creating call under its key.
  A `done`, an `edit`, an `rm`, and an `mv` are sent once, because nothing
  records their outcome and a second attempt could write twice.
- `login` is email and password, then the org (choose one with `--org`
  when you belong to several); the session token is kept in
  `$TADAS_HOME/session.json` (default `~/.config/tadas`, mode 600). The
  CLI signs in as a person, so it follows the person's rules: one session
  at a time, in one org. `orgs` lists the orgs the person belongs to, read
  with that session. `switch <slug>` presents the kept session to the
  exchange with the other org; the API ends it in the same write and the
  file keeps the new one, so the CLI never holds two. Only the kept session
  switches: `TADAS_TOKEN` is the environment's credential, not the CLI's to
  end. There is no `signup` command; a person signs up in the portal, or
  locally through `make seed`.
  `TADAS_TOKEN` in the environment wins over the file and may hold an api
  key; `TADAS_API_URL` or `--api` names the API (default
  `http://127.0.0.1:8000`). A token goes only to its own API: the file's
  to the API that issued it, and an `--api` or `TADAS_API_URL` naming
  another one is refused (exit 2); `TADAS_TOKEN` to the API named, never
  to the file's; `TADAS_HTTP_TIMEOUT_SECONDS` bounds every call
  and the socket's open (default 30), `TADAS_HTTP_RETRIES` how many extra
  attempts a retryable failure gets (default 2, and 0 sends every call
  exactly once) and `TADAS_HTTP_RETRY_BACKOFF_SECONDS` the wait before the
  first of them (default 0.25, doubling from there). `logout` revokes the
  session the file keeps, at the API that issued it, and forgets the file
  whatever the API answers; a session already gone is not an error, and
  `TADAS_TOKEN` is left alone.
- `listen` opens the socket on a single-use ticket, subscribes to
  `entity_changed`, and tells each push after reading the task it names;
  the push says who and what, the record says the rest. A deleted task is
  told from what the listener remembers. A gap in the stream is replayed
  from `/v1/events`, a dropped socket reconnects with a jittered backoff
  and replays the same way, so nothing is skipped. A task read that fails
  at the wire or with a 5xx on every attempt is told on stderr and that
  change is skipped; the task's next change shows its state. Only a dead
  credential ends the listener.
- `src/tadas/apps/cli/model.py` is pure and unit tested: how a change is
  told, which tasks are mine, how a short id resolves.
- The short id is the tail of the task's id, because ids are time-ordered
  and every task made in the same minute shares a head.

## Test

```bash
uv run pytest -q apps/cli/tests
```

The tests run the commands against the whole API in-process (memory
storage, the local infra root) and the listener over a scripted channel.
The socket itself is exercised against `make up` by `make demo-cli-gif`.
