# Tadas portal

The product's browser app: React, TypeScript, Vite, TanStack Query,
Zustand, one realtime channel.

## Conventions

- Feature code never calls `fetch` and never imports `schema.d.ts`;
  everything goes through `@tadas/api-client` (`src/app/api.ts` holds
  the one instance). ESLint enforces both.
- Server state lives in TanStack Query (`src/queries/`), with keys from
  `src/queries/keys.ts`. The first key element is the entity name the
  server pushes, so a push invalidates by convention.
- Client state lives in Zustand (`src/store/`): the session token, the
  connection status.
- One screen is `src/features/<screen>/`: `<Screen>Page.tsx` renders,
  `use<Screen>Vm.ts` decides, `<screen>Model.ts` computes and is unit
  tested without React.
- `src/realtime/RealtimeProvider.tsx` owns the one socket. Envelopes
  (`envelopes.ts`) route into the query cache (`router.ts`), never into
  components. The ping interval comes from
  `deployment/realtime-timeouts.json`.
- Design tokens and the kit live in `src/design/`; the operator console
  imports them from here.

## Run

```bash
pnpm install
pnpm --filter @tadas/portal dev     # http://localhost:5173, API at VITE_API_URL
pnpm --filter @tadas/portal test
```
