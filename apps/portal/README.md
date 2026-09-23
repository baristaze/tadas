# Tadas portal

The product's browser app: React, TypeScript, Vite, TanStack Query,
Zustand, one realtime channel.

## Conventions

- Feature code never calls `fetch` and never imports `schema.d.ts`;
  everything goes through `src/api/` (the types generated from the
  committed `openapi.json` behind the facade `types.ts`, and the one
  transport client; `src/app/api.ts` holds the one instance). ESLint
  enforces both. `make openapi` regenerates `schema.d.ts`. The object
  store is the one other place a request goes, through a URL the API
  signed and handed over: `src/api/store.ts` posts a form to it or
  fetches a link from it, with a deadline of its own and nothing of the
  API client's (no bearer, no retry), since the form or the link is the
  credential.
- A task's files are `src/features/attachments/`, shown in the task's
  open view: dropped or picked, started on the API, posted straight to
  the store, confirmed, listed with name, size, and type, downloaded and
  saved under the file's own name, removed. Each file with a preview
  shows it inline, through the store's short-lived inline link: an image
  as a thumbnail that opens larger in the page, a video and a sound in
  the browser's player, a PDF in a frame; anything else (text, documents,
  archives) is download-only, and download stays beside every preview.
  Someone who cannot write opens a task's files read-only with its
  `files` link. The flows
  (`transfer.ts`) take their effects as arguments and run in a test
  without React. Where the store cannot take a form, the bytes go
  through the API instead. The settings page shows the org's storage
  used.
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
  `Banner`; a view-model never swallows a mutation error), the upgrade
  dialog a write refused for a plan's bound opens instead of a notice
  (`upgrade.ts`, opened from the query cache's one mutation error hook and
  rendered once by `src/features/billing/UpgradeDialog.tsx`), and the
  preferences kept across visits (`preferences.ts`, the task scope and
  the theme, persisted in local storage). The token is kept in memory and in the
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
- A person signs in through WorkOS AuthKit, which the API fronts. `/login`
  is the address WorkOS sends a person to when a sign-in did not start here
  (an invitation's link, a bookmarked sign-in page), and it starts one at
  once, with no form (`src/features/sign_in/`): it keeps a fresh random
  `state` in the tab's session storage (`src/store/signInState.ts`), with
  the page to come back to and an invitation's token, asks the API for the
  authorization URL for this origin's `/auth/callback`, and sends the
  browser there. `/auth/callback` goes on only with a state this tab
  stored, consumed once, so a code started anywhere else is refused; it
  hands the code to the API, which exchanges it with WorkOS server-side,
  and a person nobody knew is signed up by it, with their personal org. A
  tab that just signed out waits on `/login` for the person to ask, rather
  than being signed straight back in. `/sign-in` and `/sign-up` still lead
  there. The local stack also serves `/login/dev`, a sign-in by address
  alone for the seeded people and anyone a developer names, offered only
  when the runtime config says `devSignIn` (true locally, absent in the
  cloud) and refused by a deployed API.
- One tenant at a time. Every sign-in answers with the person's places:
  one goes straight in, several show a picker with the personal org first,
  none says so. The exchange turns the choice into the one session the tab
  holds. The org chip in the chrome (`src/app/OrgChip.tsx`) shows the
  current org, marks a personal one, and opens a menu: the other places to
  switch to, and a new team org (`/orgs/new`, `src/features/new_org/`: a
  name and an optional short name, which the server makes from the name
  when it is left empty). A switch presents the current session to the
  exchange, which the server ends in the same write, and `adoptSession`
  then drops the old tenant (`forgetSession`: the token and every cached
  answer) before the new session is set. A new team org is created under
  an idempotency key and then switched into the same way. The token change
  reopens the realtime socket; a late 4401 from the old socket signs
  nothing out, since it belongs to a token the tab no longer holds.
- Settings, for a member who manages members: an invitation by email and
  role (at most their own, never owner), which WorkOS sends, and the
  pending ones to send again or revoke. A team org's settings also open
  WorkOS's admin portal, where the org's admin connects their identity
  provider for single sign-on or proves a domain; a personal org has none.
- Design tokens and the kit live in `src/design/`; the operator console,
  when it is built (ADR 0010), imports them from here. A colour or a
  shadow token is a CSS custom property, and `theme.css` gives each its
  light and its dark value, so an inline style follows the theme with no
  code of its own. `kit.css` holds what inline styles cannot say (hover,
  focus, the dragged row). Feature code styles through the tokens and the
  kit, never a literal colour. Every text colour meets WCAG AA in both
  themes. The theme follows the system until the person picks one with
  the toggle in the chrome (system, light, dark, in turn); the pick is a
  `data-theme` attribute on the root, set before the app renders. The
  typeface is Inter, bundled with the build (`@fontsource-variable/inter`),
  so the page loads no font from another origin.

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
`make stack-up` does. After `make seed`, sign in at `/login/dev` as
`owner@example.test` (owner) or `bob@example.test` (member), by address
alone; `/login` signs a person in through WorkOS, once the API holds a
WorkOS key. See the root README for every local URL.

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
after 250 to 500 ms. `retryAttempts: 0` sends every call exactly once. `devSignIn: true` offers
the local sign-in at `/login/dev`; a deployed config leaves it out, and
locally, with no file, it is on unless `VITE_DEV_SIGN_IN=false`. How the
build reaches the cloud is in `deployment/terraform/modules/README.md`.
