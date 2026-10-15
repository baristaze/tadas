# ADR 1014: The Stripe client tells a refused key from a refused request

**Status**: accepted (2026-10-14)

## Context

[ADR 0051, A refused key is unavailable; a refused request is refused](0051-a-refused-key-is-unavailable-a-refused-request-is-refused.md)
has a provider's client raise a refusal of the key as unavailable and a
refusal of the request as refused, and has work read the outcome by
status. Tadas calls a second provider from requests and from work:
Stripe, the payment processor. A client that reads both refusals as one
leaves work no way to tell them apart: it either fails for good on a
key a person could fix, or retries a request that can never pass.

## Decision

The Stripe client tells the two apart on every call:

| Stripe answers | Raised | Status, code |
|----------------|--------|--------------|
| `401`, `403` (the key) | `PaymentsKeyRefused`, a `ProviderUnavailable` | `503`, `payments_key_refused` |
| `429`, after the SDK's own retries | `ProviderUnavailable` | `503`, `unavailable` |
| No answer | `BackendUnreachable` | `503`, `unavailable` |
| `400`, `402`, `404`, an idempotency key reused (the request) | `PaymentsRefused` | `502`, `payments_refused` |
| `5xx`, anything else | `BackendFailed` | `500`, `backend_failed` |

A refused key is logged at error, naming the call, so the log says
which permission to add.

The processor's calls go under the system's own credential,
`SYSTEM_SCOPE` and `TADAS_STRIPE_RUNTIME_KEY`, so a `503` marks the
processor out for every tenant
([ADR 0088](0088-a-providers-outage-is-a-shared-signal.md)).
`SYNC_SEATS` reads its outcome as `DELETE_ACCOUNT` and `DELETE_ORG` do.

## Consequences

A checkout, the portal, a cancel, or a resume under a refused key
answers `503` `payments_key_refused`, not `502` `payments_refused`. The
portal says billing is unavailable right now, with the request's
reference. A throttle answers `503` `unavailable`, not `500`
`backend_failed`. A refusal of the request answers `502`.

The billing read asks Stripe nothing. The webhook consumer leaves a
delivery on the queue for any failure.
