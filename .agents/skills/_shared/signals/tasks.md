# Signals: tasks

The org's tasks: its lists, a task's reminder on its due date, the
import of a file of rows, the daily cleanup of old done tasks, and the
files attached to a task.

## Kinds

- `TASK_REMINDER`: a task's due date came, so the team hears of it at
  nine in the morning of that date, in the time zone of the person the
  task is for; before then the item parks. A reminder whose task closed
  or moved its date sends nothing. One that failed for good leaves its
  task unreminded, and nothing else waits on it.
- `UNASSIGN_TASKS`: a person left an org when their account was
  deleted, so their open tasks there go unassigned, run under their
  name. One that failed for good leaves those tasks assigned to the
  person who left.
- `task_import`: the tasks of a CSV file the org uploaded, a hundred
  rows a step. It parks on the plan's bound of active tasks, which is
  the tenant's own limit and not a finding, and the processor's
  delivery of a higher plan wakes it. It fails on a bound of the file,
  the person's to fix (`file_too_large`, `too_many_rows`, `not_csv`,
  `no_title_column`, `file_gone`), or as a defect, which is ours.
- `task_cleanup`: the archive of an org's done tasks past the archive
  age, five hundred a step. The sweep opens one per org per day, so its
  start is the sweep opening that org's day. One that has not succeeded
  within a day is a step the queue keeps retrying.

## Outcomes

- `tasks`: `detach_failed`, the attachments of a deleted task that did
  not go with it. They stay out of every list, still count toward the
  tenant's usage, and the sweep's purge of deleted tasks asks again.
- `orchestrations`, for the two kinds above: `task_import_<state>` and
  `task_cleanup_<state>`, as the orchestrations file says.

## Log lines

- `task_import <id> in org <org> failed: <reason>` at `WARNING` in
  `/tadas/<env>/maintenance`: an import that met a bound of its file,
  with the reason. The person fixes the file and imports again; not a
  finding.
- `the attachments of deleted task <id> were left live` at `ERROR` in
  `/tadas/<env>/api`: a delete whose files did not detach
  (`tasks`/`detach_failed`); the sweep asks again.
- `the attachments of task <id> are kept for the next purge` at `ERROR`
  in `/tadas/<env>/maintenance`: the sweep's retry failed too, so the
  deleted task stays for the next pass. The same task on pass after
  pass is a finding, with the task's id.

## Report

```markdown
- Tasks: <n> created in the last day, as the size counts them; attachments left live <n>
- Imports: <started, parked on the plan, succeeded, failed on the file, defects>; cleanups <opened, succeeded, failed>
```
