# ADR 0025: An apply returns a scaled service to its floor

**Status**: accepted (2026-09-22)

## Context

OPS-17 (Operations, Scale-Out as a Lever) leaves a service's desired
count to autoscaling: the guideline puts `desired_count` in
`ignore_changes`, so an apply never undoes what the policy scaled.

Autoscaling is off by default here. With it off, an ignored count makes
the root's number a lie: a change to `desired_count` in the root would
apply nothing.

## Decision

`desired_count` stays out of `ignore_changes`, as the service module
says. A change to the count applies, with autoscaling on or off, and
nothing in the state disagrees with the file. With autoscaling on, an
apply returns a scaled service to its floor, and the policy raises it
again within its cooldown while the load lasts.

## Consequences

- A deploy is already a roll, and a few minutes at the floor is the
  price of one. An environment that cannot afford the dip raises its
  floor in the same pull request.
- A check against the guideline's text reads the missing
  `ignore_changes` as this decision, not as drift.
