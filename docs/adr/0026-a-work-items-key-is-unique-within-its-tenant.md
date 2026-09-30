# ADR 0026: A work item's key is unique within its tenant

**Status**: accepted (2026-09-22)

## Context

ASY-16 (The Work Queue) asks for a unique index on `(org_id,
idempotency_key)`, and calls one on the key alone a violation: a key
another tenant holds would answer `KEY_EXISTS`, and the read-back under
this tenant would find nothing.

The checker's coverage of the rule is partial. It reads a unique index
on the key alone and nothing else, so it reports the shape the lens
asks for.

## Decision

`queue.work_items` carries `uq_work_items_org_id_idempotency_key`, the
unique index on `(org_id, idempotency_key)`, led by the tenant, and no
unique index on the key alone. Two tenants may hold one key. A
`KEY_EXISTS` is this tenant's own retry, and `read_item_by_key` reads
the item back under the tenant.

`[[tool.arch-check.exception]]` in `pyproject.toml` excuses ASY-16 on
`om/src/tadas/om/work/storage/tables/work_items.py` and names this
record.

## Consequences

- A review that reads ASY-16 against the work items table finds the
  index the lens names, and cites this record for the exception.
- The exception goes when the checker reads the tenant-led index, and
  the checker reports the entry as stale that day.
