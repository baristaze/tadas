# ADR 1018: A task's push names the version it wrote

**Status**: accepted (2026-10-14)

## Context

[ADR 0061, A push names the version its change wrote](0061-a-push-names-the-version-it-wrote.md)
has a record that carries a version name it in the outbox row of every
change, so a client that holds the record at that version need not
read it. Tasks carry a version, and every write names the one it read
([ADR 0009](0009-tasks-carry-a-version.md)). A push about a task names
the task, and every open tab reads that one task
(`GET /v1/tasks/{id}`), the tab that made the write included.

## Decision

**A task's outbox row names the version its change wrote, and the push
carries it.** The create, the edit, the move, the delete, the restore,
a bulk change, an imported task, and the sweep's respace name it. The
reminder and the daily archive write the version in storage, so the
manager does not know it, and their pushes name none.

**A tab reads a task only when it does not hold the version the push
names.** It holds a task when it placed a write's answer or a read's at
that version or a newer one. Placing a task writes it into every cached
list, so every list the tab holds shows it. An optimistic edit is not
held, a task a 404 took out is not held, and a task seen only in a list
read is not held, since another scope's list may be older. The check
runs when the hint's window closes, so the push of the tab's own write
counts even when it arrives before the write's answer.

## Consequences

The tab that made a write reads nothing for it. Every other tab reads
the one task. A reminder and the daily archive still cost each open tab
a read of the task.
