# Tadas portal

The product's browser app: React, TypeScript, Vite, TanStack Query,
Zustand, one realtime channel.

## Conventions

- Feature code never calls `fetch` and never imports `schema.d.ts`;
  everything goes through `src/api/` (the types generated from the
  committed `openapi.json` behind the facade `types.ts`, and the one
  transport client; `src/app/api.ts` holds the one instance). ESLint
  enforces both. `make openapi` regenerates `schema.d.ts`.
- Server state lives in TanStack Query (`src/queries/`), with keys from
  `src/queries/keys.ts`. The first key element is the entity name the
  server pushes, so a push invalidates by convention.
- Client state lives in Zustand (`src/store/`): the session token, the
  connection status, the transient notices a failed write leaves
  (`notices.ts`, rendered by `src/app/Notices.tsx` over the kit's
  `Banner`; a view-model never swallows a mutation error). The token is
  kept in memory and in the tab's session storage, so a reload survives
  and a closed tab forgets; never in local storage.
- One screen is `src/features/<screen>/`: `<Screen>Page.tsx` renders,
  `use<Screen>Vm.ts` decides, `<screen>Model.ts` computes and is unit
  tested without React.
- `src/realtime/RealtimeProvider.tsx` owns the one socket; the loop
  itself (ticket, reconnect with backoff, the stream cursor and its
  replay) is `channel.ts`, without React, run in its test over a fake
  socket and fake timers. A socket counts as connected once the hello
  frame arrives, so a server that accepts and closes at once still
  backs off. Envelopes (`envelopes.ts`) route into the query cache
  (`router.ts`), never into components. The ping interval comes from
  `deployment/realtime-timeouts.json`.
- Design tokens and the kit live in `src/design/`; the operator console
  imports them from here.

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
`bob@example.test` (member), both `tadas-local`, after `make seed`; see the
root README for every local URL.

## Configuration

`src/app/config.ts` loads `/config.json` before anything renders. In the
cloud that file exists, written per environment by Terraform (`apiUrl` is the
environment's API, e.g. `https://api.tadas.fyi`), so one build serves every
environment. Locally there is none, and `VITE_API_URL`,
`VITE_SENTRY_DSN`, and `VITE_SENTRY_ENVIRONMENT` apply instead. The file may
also name `requestTimeoutMs`, the deadline the transport client puts on every
call; without it, and locally, the deadline is 30 seconds. How the build
reaches the cloud is in `deployment/terraform/modules/README.md`.
