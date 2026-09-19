# Tadas CLI

The product from the terminal, in two modes. Command mode does one thing
and returns: `add`, `ls`, `edit`, `done`, `reopen`, `rm`, `mv`. Realtime
mode stays: `listen` prints every change the team makes as it happens, one
line each, over the same channel the portal uses.

```bash
uv run tadas login --email bob@example.test   # prompts for the password
uv run tadas add "Migrate DB" --assignee me
uv run tadas ls                               # open tasks; --done, --mine, --json
uv run tadas done 8b949fce                    # the short id `ls` shows
uv run tadas listen                           # the team's tasks; --mine for yours
```

## Conventions

- Dumb client. The CLI never decides; it calls the API through the one
  Python client (`clients/python/`, `tadas.client`) and shows the answer.
  A refusal is printed as the API's own code and message, with the
  request id.
- One command, one call, one exit code: 0 done, 1 the API refused, 2
  usage, 3 not signed in, 4 the API is unreachable.
- A creating call (`add`) carries an idempotency key, minted by the client.
- `login` is email and password, then the org (choose one with `--org`
  when you belong to several); the session token is kept in
  `$TADAS_HOME/session.json` (default `~/.config/tadas`, mode 600).
  `TADAS_TOKEN` in the environment wins over the file and may hold an api
  key; `TADAS_API_URL` or `--api` names the API (default
  `http://127.0.0.1:8000`).
- `listen` opens the socket on a single-use ticket, subscribes to
  `entity_changed`, and tells each push after reading the task it names;
  the push says who and what, the record says the rest. A deleted task is
  told from what the listener remembers. A gap in the stream is replayed
  from `/v1/events`, a dropped socket reconnects with backoff and replays
  the same way, so nothing is skipped.
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
