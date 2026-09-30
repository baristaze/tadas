# Tadas company site

The public landing page at `https://tadas.example` (and
`https://staging.tadas.example` on staging): the product's name, one line
about it, and the way into the portal. `404.html` is the page a missing
address gets.

It is HTML and CSS built by Vite, with no script. `src/site.css` imports the
portal's `theme.css`, so the two share one palette and follow the system's
light or dark. The page loads nothing from another origin.

`src/links.ts` fills `%APP_URL%`, `%SITE_URL%`, and `%GITHUB_URL%` from
`deployment/cloud/environments.json`, once per environment; a placeholder
nothing fills fails the build.

```bash
pnpm --filter @tadas/site dev      # http://localhost:5174, links to the local portal
pnpm --filter @tadas/site build    # dist/staging and dist/production
pnpm --filter @tadas/site test
```
