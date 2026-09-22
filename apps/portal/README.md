# Tadas portal

The product's browser app: React, TypeScript, Vite, TanStack Query,
Zustand, one realtime channel.

## Conventions

- Feature code never calls `fetch` and never imports `schema.d.ts`;
  everything goes through `src/api/` (the types generated from the
  committed `openapi.json` behind the facade `types.ts`, and the one
  transport client; `src/app/api.ts` holds the one instance). ESLint
  enforces both. `make openapi` regenerates `schema.d.ts`.
- The app's one retry is the transport client's, and no other layer has
  one: TanStack Query's is off in `src/app/queryClient.ts`, so a failing
  API sees these attempts and no multiple of them. Only a failure that
  can differ on a second attempt goes again (the deadline, a connection
  that failed before an answer, and a 502, 503, or 504); a refusal is a
  decision and is told to the caller. Only a read and a creating POST
  under its idempotency key may be sent twice, so a write the gateway
  does not record the outcome of is sent once. The rules and the curve
  are `src/api/retry.ts`: the delay doubles, half of each wait is jitter,
  a `Retry-After` the server sends lengthens a wait to it (never past the
  cap), and the count and the first delay come from the runtime config.
- Server state lives in TanStack Query (`src/queries/`), with keys from
  `src/queries/keys.ts`. The first key element is the entity name the
  server pushes, so a push invalidates by convention; an entity the
  convention does not reach on its own (a membership, read through
  `me` and the person's list of places; a user, read through `me` as
  well as its own list) is named in the router's table instead.
- Client state lives in Zustand (`src/store/`): the session token, the
  connection status, the transient notices a failed write leaves
  (`notices.ts`, rendered by `src/app/Notices.tsx` over the kit's
  `Banner`; a view-model never swallows a mutation error), and the
  preferences kept across visits (`preferences.ts`, the task scope,
  persisted in local storage). The token is kept in memory and in the
  tab's session storage, so a reload survives and a closed tab forgets;
  never in local storage, which is for preferences only. No feature
  reads a storage directly; a store does.
- One screen is `src/features/<screen>/`: `<Screen>Page.tsx` renders,
  `use<Screen>Vm.ts` decides, `<screen>Model.ts` computes and is unit
  tested without React.
- `src/realtime/RealtimeProvider.tsx` owns the one socket; the loop
  itself (ticket, reconnect with backoff, the stream cursor and its
  replay) is `channel.ts`, without React, run in its test over a fake
  socket and fake timers. The reconnect delay doubles to a cap and half
  of each wait is jitter, because a socket drops for a shared reason: a
  bare curve would bring every tab back at the same instant. A socket
  counts as connected once the hello frame arrives, so a server that
  accepts and closes at once still backs off. Envelopes (`envelopes.ts`)
  route into the query cache (`router.ts`), never into components. The
  ping interval comes from
  `deployment/realtime-timeouts.json`.
- One tenant at a time. A person enters through sign-in (`/sign-in`) or
  sign-up (`/sign-up`: email, name, password, the org and its short
  name), and both answer with the person's places: one goes straight in,
  several show a picker, none says so. The exchange turns the choice into
  the one session the tab holds. The org chip in the chrome
  (`src/app/OrgChip.tsx`) shows the current org and, with more than one
  place, opens the list and switches: the exchange is presented with the
  current session, which the server ends in the same write, and
  `adoptSession` then drops the old tenant (`forgetSession`: the token
  and every cached answer) before the new session is set. The token
  change reopens the realtime socket; a late 4401 from the old socket
  signs nothing out, since it belongs to a token the tab no longer holds.
- Design tokens and the kit live in `src/design/`; the operator console,
  when it is built (ADR 0010), imports them from here.

## Run

```bash
pnpm install
pnpm --filter @tadas/portal dev     # http://localhost:5173, API at VITE_API_URL
pnpm --filter @tadas/portal test
```

`make stack-up` from the repository root also serves a production build
in a container at http://localhost:55173, from
`deployment/docker/portal.Dockerfile`. The API address is compiled into
that bundle (build argument `VITE_API_URL`, default
`http://127.0.0.1:8000`), so a change to it needs a rebuild, which
`make stack-up` does. Sign in as `owner@example.test` (owner) or
`bob@example.test` (member), both `tadas-local`, after `make seed`, or
create an account at `/sign-up`; see the root README for every local URL.

## Configuration

`src/app/config.ts` loads `/config.json` before anything renders. In the
cloud that file exists, written per environment by Terraform (`apiUrl` is the
environment's API, e.g. `https://api.tadas.fyi`), so one build serves every
environment. Locally there is none, and `VITE_API_URL`,
`VITE_SENTRY_DSN`, and `VITE_SENTRY_ENVIRONMENT` apply instead. The DSN is
the product's one tracker project in every environment; the environment the
page sends on each event is what separates them. The file may
also name `requestTimeoutMs`, the deadline the transport client puts on every
call; without it, and locally, the deadline is 30 seconds. It may name
`retryAttempts` and `retryBaseDelayMs` the same way, the extra attempts a
retryable failure gets and the wait before the first of them; without them the
client makes 2 extra attempts, the first after 125 to 250 ms and the second
after 250 to 500 ms. `retryAttempts: 0` sends every call exactly once. How the
build reaches the cloud is in `deployment/terraform/modules/README.md`.
