# ADR 1003: The company site lists the plans in its own HTML

**Status**: accepted (2026-10-14)

## Context

[ADR 0002, Technology choices as adopted](0002-technology-choices.md)
makes the company site, `apps/site`, HTML and CSS on Vite with no
script, since a page with no state, no API call, and no socket has
nothing to render in a client. Tadas sells plans, and a visitor reads
them before signing up. A privacy page has to be one link away.

## Decision

The site is three pages: the landing page, the privacy page, and the
not-found page. The landing page says what Tadas is, lists the plans
with their prices and bounds, and leads into the portal.

The plans are written into `apps/site/index.html`, never read from the
API. So the site stays a set of pages with no API call, and the
substitution holds for all three.

## Consequences

The numbers the system enforces are one table in `billing.rules`
([ADR 0031](0031-plans-are-levers-and-the-processor-is-mirrored.md)).
The page repeats them by hand. `apps/site/src/site.test.ts` pins the
prices and bounds the page states, and reads no `billing.rules`, so a
change to a plan changes the page and that test in the same pull
request.

The same test holds each of the three pages to no script and nothing
from another origin.
