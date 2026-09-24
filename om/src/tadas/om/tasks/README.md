# Tasks

The to-do items a team creates, works, and closes. This is one of the
seven kinds of thing [Tadas is made of](../../../../README.md).

## The nouns

- **Task**: a title, notes, a status (open or done), an assignee, a
  position in the open list, a due date, and a version. It remembers
  who created it, who last changed it, and when its reminder went out.
- **Filter**: which tasks a list shows. *Team* shows every task of the
  org. *Mine* shows the tasks assigned to me, plus the unassigned ones I
  created.
- **Cursor**: where the previous page ended, so the next page starts
  right after it. The open list pages by position, the done list by the
  time of the last change.
- **Page**: the tasks of one page and whether another page follows.
- **Attachment**: a [file](../media/README.md) kept with a task.

## What can happen

- **Create.** A new task is open and goes to the top of the open list.
- **List the open tasks**, in the order the team arranged them, top
  first, a page at a time.
- **List the done tasks**, newest first, a page at a time.
- **Count the open tasks** a filter shows, without reading them: what a
  short list, like Slack's, says about the rest.
- **Read one task.**
- **Edit**: the title, the notes, the assignee, the status. A task
  reopened from done goes back to the top of the open list.
- **Move** an open task right after another one, or to the top.
- **Delete.** The task is hidden, not erased. Its attachments are
  removed with it.
- **Attach a file**, list a task's files, and remove one. The upload
  itself, its confirm, and its download are the file's own.
- **Set, move, or clear the due date.** Setting it schedules one
  reminder on the morning of that day; moving it schedules a new one;
  clearing it schedules none.
- **Remind.** At nine in the morning of the due date, the task is marked
  reminded and every open screen of the org hears of it; so does the
  org's Slack channel, when one is connected.
- **Sweep.** Deleted tasks are erased for good after the retention.

## The rules

- **The plan bounds the active tasks.** An active task is one that is
  neither done nor deleted. An org on a plan with a bound (ten on Free)
  is refused the task past it, and a reopen past it, with a refusal
  that names the plan that lifts the bound; a done or deleted task
  makes room again. Nothing is ever deleted for a bound
  ([billing](../billing/README.md)).
- **Every write names the version it read.** A task carries a version
  number, and every edit, move, and delete says which version the
  caller saw. If the stored task has moved on, the write is refused
  and nothing is merged; the caller reads again. An edit that raced a
  delete finds the task gone and cannot bring it back.
- **Some fields are never the caller's.** An edit changes the title,
  the notes, the assignee, and the status. Who made the task, whether
  it is deleted, its place in the open list, and its version stay as
  stored, whatever the edit sends; a move places a task, and every
  write sets the version.
- **The fractional position.** Open tasks are ordered by a number. A
  new task takes one less than the smallest, so it lands on top. A
  task moved after another takes the midpoint between that task and
  the one that follows it, or one more than it when it is last. So a
  move changes one task and no other.
- **Renumbering.** Halving a gap runs out of room eventually. When the
  midpoint equals a neighbour, the whole open list is renumbered with
  whole numbers in one step, every task whose position changed
  announced, and the gaps are wide again.
- **A page is a page.** A page holds at most two hundred tasks, and
  "another page follows" is a fact about the rows, not a guess.
- **Assignment is checked when it changes.** Assigning a task to
  someone requires them to be a member now. Marking a task done or
  editing its title does not re-check an assignee who has since left;
  clearing the assignee is always allowed.
- **Mine is about nobody else.** The person the *mine* filter is about
  is always the caller.
- **A file is attached to a live task.** A deleted task, or another
  org's, takes no file and lists none; a file is removed only from the
  task it is attached to.
- **A task's delete does not wait on its files.** The task is deleted
  first and its attachments after it; when removing them fails, the
  delete still stands, the failure is logged and counted, and the files
  stay out of every list while still counting toward the storage used.
- **A due date is a date.** A task is due on a day, never at an hour.
  The API takes `YYYY-MM-DD` and refuses a time.
- **The reminder keeps the person's morning.** A date has no hour, so
  the reminder takes one: nine in the morning of the due date, in the
  time zone of the person the task is for. That is the assignee, or the
  creator when the task is unassigned. A person's time zone is the one
  their browser reports when they sign in to the portal; with none
  recorded, the reminder keeps UTC's morning. The zone is read when the
  reminder runs, so a task handed to someone else, or a person who
  moved, is still met on their own morning.
- **A reminder is for the due date it was set for.** It goes out only
  while the task is open, not deleted, still due on that date, and not
  yet reminded, all checked in one write. So a reminder for a date that
  was moved or cleared, or for a task finished or deleted meanwhile,
  never goes out, and a reminder goes out once.
