# ADR 0001: The root package is `tadas`

**Status**: accepted (2026-09-16)

## Context

Every Python distribution in the monorepo shares one import root, so a
namespace reads as `<root>.om.<ns>`, `<root>.infra.<capability>`, and
`<root>.services.<svc>`. A root named `platform` would shadow the
standard-library module of that name.

## Decision

The root package is `tadas`, the product's name. It is a namespace
package: no distribution has `tadas/__init__.py`, so `tadas-om`,
`tadas-infra`, and every service and worker add subpackages to the same
root.

## Consequences

Imports read `from tadas.om.base import Platform`. Every new distribution
uses the `src/tadas/...` layout and never adds `tadas/__init__.py`.
