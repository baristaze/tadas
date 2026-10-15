# ADR 1017: An API key's socket follows the plan's lever on keys

**Status**: accepted (2026-10-14)

## Context

[ADR 0058, A socket asks again, and its pong answers from the bus](0058-a-socket-asks-again-and-its-pong-answers-from-the-bus.md)
checks a socket opened under an API key as the key's every request is
checked: the key, and the principal behind it. Tadas's plans are levers
([ADR 0031](0031-plans-are-levers-and-the-processor-is-mirrored.md)),
and one of them is whether an org may use API keys at all.

## Decision

**The recheck reads the plan's lever on keys too.** The plan comes from
the billing account read with the principal (`read_key_principal`), so
the check costs no read of its own. After a downgrade to a plan without
keys, the recheck refuses the key with `plan_limit_reached`, and the
socket closes with 4401, as a revoked key's does. The key is kept, and
works again on a plan with keys.

**The bus is the fast path here too.** A plan change writes
`billing.account.updated`, which every process hears. It carries no
plan, so it closes nothing itself: it wakes, at once, the recheck of
every socket an API key of that org opened, and the recheck reads the
plan. An auth session's socket is not woken. When the bus loses the
message, or a paid plan runs out at its period's end with no message
at all, the recheck interval bounds the socket as it bounds a lost
revocation.

## Consequences

| Per API key socket | |
|---|---|
| Recheck reads | `read_api_key`, `read_key_principal` |
| Recheck cost | 2 transactions, 6 round trips |
| Worst case after a downgrade | at once on the bus; one interval (5 minutes) without it |
