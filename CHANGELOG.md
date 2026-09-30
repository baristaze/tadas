# Changelog

The latest release has its entry here. It lists what changed since the
previous tag. A project that clones Tadas at a release checks out its
tag, such as `git clone --branch v0.7.0`.

## 0.14.0 (2026-09-30)

A clone of Tadas at this tag finds a session that keeps its sign-in's
deadline through every switch, webhook routes that refuse a header no
signer writes, and log lines, spans, and error events that name a
request by its route, never its path. The pin moves to guideline v0.45.0
by merging the scaffold. No route, wire type, screen, or migration
changes, and nothing is reversed.

- **A session made from a session keeps its deadline.** A switch into
  another org, and the landing after a team org's deletion, take the
  earlier of the presented session's deadline and a full lifetime. Only
  the exchange of a sign-in starts the 30 days, so a person signs in
  again when the deadline of their sign-in passes. ADR 0063 says so.
  (#194)
- **An enqueue asks for its kind's permission.** `WorkManagerImpl.enqueue`
  requires the permission `WORK_ENQUEUE_PERMISSIONS` gives the kind, and
  refuses a kind the table lacks. The table names all nine kinds, and a
  test lists the kinds the code asks for against it. (#194)
- **A webhook header no signer writes is a bad signature.** A signature
  with a byte past ASCII, a timestamp `int` refuses, and one a float
  cannot hold answer 400 on `/webhooks/identity` and `/webhooks/stripe`
  and 401 on Slack's two signed routes, never 500. A one-time code, an
  `If-Match` version, a `Content-Length`, Slack's retry number, and
  Slack's `Retry-After` are read as ASCII digits alone. (#194)
- **A log line, a span, and an error event name a request by its
  route.** Each names the route's template, never the path, and the
  lost-marker warning names an idempotency key by a digest. A span
  records no exception text, an error event keeps the request's method
  alone, and every engine hides its bound parameters. The Slack twin
  logs a post's length, never its text. (#194)
- **The ops skills keep less.** `ops-root-cause` keeps ids, kinds, and
  timestamps from the operator plane, never a name. The skills that
  hold a token pre-approve the ops command alone, and the error tracker
  reader sends no sort the tracker refuses. `docs-compact` tells an
  expand and contract in flight by the tree. (#194)
- **The guideline pin moves to v0.45.0.** `main` merges the `scaffold`
  branch at v0.45.0. (#194)

Every release's notes stay on the repository host: <https://github.com/baristaze/tadas/releases>.
