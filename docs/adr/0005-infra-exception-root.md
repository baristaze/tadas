# ADR 0005: Infra has its own exception root

**Status**: accepted (2026-09-18). Follows the guideline since v0.8.0:
Exceptions gives infra a root of its own, `InfraException`, with the
same two fields, and a boundary translates both roots. It is no
deviation.

## Context

DEL-18 (Cross-Cutting Conventions, Exceptions) roots every exception
raised inside the platform at `PlatformException`. The guideline also
says the object model imports infra's interfaces and infra imports
nothing from the object model. Both cannot hold in one class hierarchy:
`PlatformException` lives in the object model, so an infra impl that
raises it imports the model.

## Decision

`tadas.infra.exceptions.InfraException` is a second root. It mirrors the
platform root with the same `http_status`, `code`, and `message` shape.
Every infra leaf (`BackendFailed`, `BackendUnreachable`, `BlobNotFound`,
`InvalidBucketKey`, `SecretNotFound`, and the rest) derives from it, and
so does every integration's error. A boundary registers one handler per
root and presents both in the same envelope.

## Consequences

Every boundary that translates `PlatformException` also translates
`InfraException`. `services/api/src/tadas/services/api/gateway/errors.py`
does, and a new service copies the pair. Code that catches "any platform error" catches
both roots or neither. The roots stay two while the platform root lives
in the object model.
