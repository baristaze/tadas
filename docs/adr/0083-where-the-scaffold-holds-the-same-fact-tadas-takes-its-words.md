# ADR 0083: Where the scaffold holds the same fact, Tadas takes its words

**Status**: accepted (2026-09-30)

## Context

Tadas is a copy of the guideline's scaffold plus its product. Its
`scaffold` branch holds the scaffold rendered as `tadas`, one release
after another, and the pin moves by merging that branch (Adopting,
Upgrade a copy of the scaffold). A merge brings in only what the
scaffold changed between two releases, so every other difference
between the branch and `main` is Tadas's own.

A line that says the same thing as the scaffold's in other words is a
conflict at every later move, and it is no product.

## Decision

**The move is a merge of the scaffold.** The pull request that carries
it merges with a merge commit, never a squash, so the render it merged
stays the base of the next move.

**Where the scaffold holds the same fact, Tadas takes its words.** That
holds for a doc, a docstring, a skill, a test, a workflow, and an ADR
alike. A sentence of Tadas's that adds the product to the scaffold's
takes both sides: the scaffold's words, and the product's beside them.

**What stays different is Tadas's.** Its product: tasks, billing,
Slack, the plans, the second queue, and what each adds to a page the
scaffold also has. The date of each ADR. And what stays out by design:
its migration chain, the scaffold's ADRs whose numbers Tadas uses for
its own, and the files it regenerates.

## Consequences

- The next pin move merges the `scaffold` branch again, from the render
  of the release `main` is pinned at.
- A generic fact written here alone is a difference the next merge has
  to resolve. In the scaffold, it comes back with the next move.
