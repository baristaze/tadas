# Tadas company site

The public landing page at `https://tadas.fyi` (and
`https://staging.tadas.fyi` on staging): what Tadas is, what it does today,
the plans, and the way into the portal. `404.html` is the page a missing
address gets.

It is HTML and CSS built by Vite, with no script. `src/site.css` imports the
portal's `theme.css`, so the two share one palette and follow the system's
light or dark. The page loads nothing from another origin.

The product visual is the README's realtime demo,
`docs/media/realtime-demo.gif`, copied into the build with a hashed name. A
dark system gets `docs/media/realtime-demo-dark.gif` instead, through the
`<picture>`'s dark source. `make demo-gif` records the light one again, and
`make demo-gif-dark` the dark one.

`src/links.ts` fills `%APP_URL%`, `%SITE_URL%`, and `%GITHUB_URL%` from
`deployment/cloud/environments.json`, once per environment; a placeholder
nothing fills fails the build.

```bash
pnpm --filter @tadas/site dev      # http://localhost:5174, links to the local portal
pnpm --filter @tadas/site build    # dist/staging and dist/production
pnpm --filter @tadas/site test
```
