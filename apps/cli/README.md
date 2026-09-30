# Tadas CLI

Tadas from the terminal. A command does one thing and returns: sign in and
out, the orgs, the task verbs (`add`, `ls`, `edit`, `done`, `reopen`, `rm`,
`mv`), a task's files (`attach`, `attachments`, `download`, `detach`), and
`import`. `listen` stays and prints every change the team makes to its
tasks as it happens.

```bash
uv run tadas login --org acme        # confirm the code in the browser
uv run tadas login --dev-email bob@example.test --org acme   # local stack only
uv run tadas whoami
uv run tadas orgs                    # * marks the session's org
uv run tadas switch fabrikam         # the old session ends
uv run tadas add "Migrate DB" --assignee me
uv run tadas add "Call the bank" --due 2026-10-01  # a date, never a time; reminded at 9:00 that day
uv run tadas edit 8b949fce --no-due  # clear the due date; --due moves it
uv run tadas ls                      # open tasks; --done, --mine, --json
uv run tadas done 8b949fce           # the short id `ls` shows
uv run tadas attach 8b949fce spec.pdf     # the type from the name, or --type
uv run tadas attachments 8b949fce         # id, size, type, name
uv run tadas download 8b949fce 1c2d3e4f   # the file's short id; --out <path>
uv run tadas detach 8b949fce 1c2d3e4f
uv run tadas import tasks.csv        # title, notes, due_on, assignee_email; follows it to the end
uv run tadas listen                  # the team's tasks, reminders among them; --mine for yours
uv run tadas logout
```

## Conventions

- A dumb client: every command calls the API through `tadas.client` and
  shows the answer. A refusal prints the API's code, message, and request id.
  A plan's bound is said in its own words, with who lifts it: an owner or
  an admin, in the portal, under Settings, Billing.
- Exit codes: 0 done, 1 the API refused, 2 usage, 3 not signed in, 4 the
  API is unreachable. A setting the environment got wrong is usage.
- The session lives in `$TADAS_HOME/session.json` (default `~/.config/tadas`,
  mode 600) and goes only to the API that issued it. `TADAS_TOKEN` wins over
  it. `TADAS_API_URL` or `--api` names the API. `TADAS_HTTP_TIMEOUT_SECONDS`,
  `TADAS_HTTP_RETRIES`, and `TADAS_HTTP_RETRY_BACKOFF_SECONDS` tune the client.
- A verb that changes a task reads it first and sends the version it read,
  so a change that raced another is refused (exit 1) and never overwrites
  it. `add` carries an idempotency key, minted by the client, so the
  client's retry may send it again. A `done`, an `edit`, an `rm`, and an
  `mv` are sent once, because nothing records their outcome and a second
  attempt could write twice.
- `listen` tells each task change after reading the task it names; the
  push says who and what, the record says the rest. A deleted task is
  told from what the listener remembers. A task read that fails at the
  wire or with a 5xx on every attempt is told on stderr and that change
  is skipped; the task's next change shows its state. When the stream no
  longer reaches back to where the listener stood, stderr says some
  changes are gone, and the listener reads every task again and goes on
  from the stream's head. Only a dead credential ends the listener.
- `import <file.csv>` uploads the file as the portal does (the form
  straight to the store, or the bytes through the API where the store
  cannot take one), starts its import, and follows it on the same channel
  `listen` uses: it reads the import once the channel is open and again on
  every push about it, printing `created N of M, skipped K` as it moves.
  It ends when the import does: exit 0 when it succeeded; exit 1 when it
  parked on the plan's active tasks (the line says who lifts the bound,
  and a plan that rises resumes the import by itself) or failed on a bound
  of the file, with the reason. The columns are `title` (needed),
  `notes`, `due_on` (`2026-10-01`), and `assignee_email` (a member), by
  header name; the file is at most 1 MB and 5,000 rows.
- `src/tadas/apps/cli/model.py` is pure and unit tested: how a change is
  told, which tasks are mine, how a short id resolves. The short id is
  the tail of the task's id, because ids are time-ordered and every task
  made in the same minute shares a head.

## Test

```bash
uv run pytest -q apps/cli/tests
```

The socket itself is exercised against `make up` by `make demo-cli-gif`.
