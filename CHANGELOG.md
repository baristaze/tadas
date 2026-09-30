# Changelog

The latest release has its entry here. It lists what changed since the
previous tag. A project that clones Tadas at a release checks out its
tag, such as `git clone --branch v0.7.0`.

## 0.16.0 (2026-09-30)

A clone of Tadas at this tag keeps the provisioner's write token in a
file of its own, which no skill that reads sources, and lets no
exception's text leave the process unless Tadas raised it as a server
error. The pin moves to guideline v0.47.0 by merging the scaffold. No
route, wire type, screen, or migration changes. One change is a
reversal in part, named below.

- **The provisioner's token has a file of its own.** Reversed in part:
  in 0.15.0 the ops env file, `~/.config/tadas/ops/<env>.env`, held
  `TADAS_PROVISIONER_TOKEN` beside the read token. It now lives in
  `<env>.provisioner.env` beside that file, read only by `tadas-ops
  traffic` and `stress`. `tadas-ops` refuses an env file that holds it
  and prints the line that moves it, the read skills pre-approve only
  the `tadas-ops` read commands they run, and `make seed` writes the
  two files. (#199)
- **An exception's text stays in the process.** The JSON log line, the
  error tracker's event, and a work item's, outbox row's, or
  orchestration's failure record keep an exception's type and frames,
  and its text only when Tadas raised it as a server error. An outbound
  call's breadcrumb keeps its method, its status, and its URL's scheme,
  host, and path, never its query, and the HTTP clients' own loggers
  write from WARNING up. Tadas's Slack lines that name an exception
  carry its frames, and a Slack transport failure names the transport's
  error by its type. (#199)
- **A Slack reply's URL stays in the process.** The URL a command's
  answer goes to lets whoever holds it post into the channel as the
  app. In 0.15.0 the Slack SDK wrote it whole in a retried reply's log
  line, and each reply's breadcrumb kept it in its path. The Slack
  SDK's loggers now write from WARNING up, and a breadcrumb names
  `hooks.slack.com` by its scheme and host alone. (#199)
- **`ops-root-cause` names each read it makes.** Each read goes through
  a `jq` that keeps what the step needs and never an exception's text.
  It reads the tracker by request id for its environment, every read by
  the window's bounds, and a tenant's open tasks, then its done ones, a
  page at a time. (#199)
- **Fixed.** The `.gitignore` anchors its build and coverage folders,
  so a namespace named `reports`, `coverage`, `build`, or `dist` is no
  longer ignored. The worker loop's tests wait on what they assert, not
  on the wall clock. (#199)
- **The guideline pin moves to v0.47.0.** `main` merges the `scaffold`
  branch at v0.47.0. (#199)

### What a copy does

- Move the provisioner's token out of the ops env file: run the line
  the first `tadas-ops` command prints, or delete
  `TADAS_PROVISIONER_TOKEN` from `~/.config/tadas/ops/<env>.env` and
  run `uv run tadas-ops token --env <env> --identity provisioner`.
  Until then every `tadas-ops` command refuses that file, `traffic`
  among them, and each skill that runs one stops with it.

Every release's notes stay on the repository host: <https://github.com/baristaze/tadas/releases>.
