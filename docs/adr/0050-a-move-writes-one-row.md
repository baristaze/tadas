# ADR 0050: A move writes one row

**Status**: accepted (2026-10-12)

## Context

An open task has a place in its org's list, and a move changes it. A
place that is a float runs out of room: a move takes the midpoint
between two neighbours, and halving a gap ends at float precision after
about fifty moves into the same gap. Every open task of the org is then
renumbered in one write.

The guideline's optimistic concurrency (Shape of an Operation) says the
manager's copy increments the version on every write, and the write
lands only while the stored row carries the version the caller names.
[ADR 0009](0009-tasks-carry-a-version.md) holds tasks to it. So a
renumber moves the version of every task it places. A person editing a
task nobody moved gets a 412, and the renumber itself fails with 412
when anyone changed any open task of the org since it read the list.

## Decision

**A place is an exact decimal rank.** `Task.rank` is a Postgres
`numeric`, a Python `Decimal`, and a string on the wire. Between two
different ranks there is always another. `tasks.rules.spread` picks the
shortest one near the middle, at most one digit longer than the longer
of the two. A create takes the whole number below the top rank. An
import takes whole numbers after the bottom one. A bulk reopen takes
whole numbers above the top, the last one named on top. A move reads
the anchor and the smallest rank past it, the moved task aside, and
takes a rank between them. It is a rank with room that never runs out,
never a renumber that leaves the version alone on the rows it only
places: that keeps a write over the whole open list.

**A move writes the moved task alone.** Its one conditional write names
the version the caller read, as every write does. No other task's row
is written, so no other version moves, and no edit of another task
meets a 412 because of a move.

**Two tasks may share a rank.** Two writers that read the same list at
once place two tasks on one rank. The list orders them by id, and the
cursor is (rank, id). There is no rank between two that tie, so a task
moved after either of them goes after both.

**A rank that grows long is respaced by the sweep.** Moves into one and
the same gap add a digit every three moves or so. Past 24 digits after
the point (`RANK_SCALE_BOUND`, seventy-odd moves into one gap), the
sweep's respace chore, per tenant, finds the rank through a partial
index that holds only such ranks. It takes the run around it: every
task between the nearest ranks of at most 12 digits, read at most 100
places each way. It gives the run short, evenly spread ranks in the
order it had, in one write conditioned on each task's version, and
each task it writes moves its version on and is announced as an edit.
A run written meanwhile is left for the next pass.

**The respace moves the version.** The version is the one signal every
client has that its copy is stale. The portal keeps a task it holds at
the same or a newer version, and places the next task it hears of by
the ranks it holds. A respace that left the version alone would leave
every open tab ordering against ranks the server no longer has, and a
task placed later would land in the wrong row. So a respace is a write
like any other, and the guideline's rule holds without a deviation.
Its cost is small: a person editing a task of the run in the instant
between their read and their write gets one 412, the answer any
concurrent edit gives. A run is only the tasks around one long rank,
at most 201, and it happens once per seventy-odd moves into one gap.

**The table keeps a float beside the rank, `position`, for the release
before.** It is an expand and contract in flight. The release before
names the position in every insert and reads it as a number, and a
client of it requires the field in a task's view. That release serves
this schema for the minutes of a roll, and again after a fast rollback
([ADR 0038](0038-a-dead-column-leaves-the-mapping-before-the-table.md)).
Four pieces serve it, and each stays until the contract step:

- **The column.** `core.tasks.position` is in the table and out of the
  mapping: no statement of the tree names it. It is not null, since the
  release before reads it as a number.
- **`tasks_position_from_rank`.** The trigger gives a row written
  without a position its rank's float. So every row the tree writes
  holds the position the release before reads.
- **`tasks_rank_from_position`.** The trigger gives a row written with
  a position and no rank the rank its position names, digit for digit:
  a float's text is the shortest that reads back as the same float. The
  release before's own integration tests insert tasks by the position
  alone, and fail without it.
- **The field.** `TaskView` sends `position`, optional and marked
  deprecated, as the rank's float, since a client of the release before
  requires it. No client in the tree reads it.

**The contract step ends it.** A revision on the core role's chain
drops the column, both triggers, and their functions. The field leaves
`TaskView` with it
([ADR 0006](0006-pre-release-compatibility.md)), and the two STO-05
exceptions in `pyproject.toml` go too. Until it lands, none of the four
pieces is dead code: removing one breaks the release before.

**The triggers are a deviation from STO-05, until the contract step.**
STO-05 says no triggers and no database functions: if something
happens, it happens in the code. The release before is code that cannot
be changed, so what it needs of the schema happens in the database.
Each trigger does one thing, copies one column into another, and goes
with the position.

## Consequences

A move is one read of the anchor, one read of the place after it, and
one write. No write touches a whole open list. `make traffic` with the
regular profile for 60 seconds meets 0 conflicts, where sessions own
their tasks.

The CLI's `listen` says "moved a task" when a task's rank changed, so
a respace shows as the platform moving the tasks of the run. The order
it shows does not change.
