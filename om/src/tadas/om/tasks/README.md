# Tasks

The to-do items a team creates, works, and closes. This is one of the
six kinds of thing [Tadas is made of](../../../../README.md).

## The nouns

- **Task**: a title, notes, a status (open or done), an assignee, a
  position in the open list, and a version. It remembers who created
  it and who last changed it.
- **Filter**: which tasks a list shows. *Team* shows every task of the
  org. *Mine* shows the tasks assigned to me, plus the unassigned ones I
  created.
- **Cursor**: where the previous page ended, so the next page starts
  right after it. The open list pages by position, the done list by the
  time of the last change.
- **Page**: the tasks of one page and whether another page follows.

## What can happen

- **Create.** A new task is open and goes to the top of the open list.
- **List the open tasks**, in the order the team arranged them, top
  first, a page at a time.
- **List the done tasks**, newest first, a page at a time.
- **Read one task.**
- **Edit**: the title, the notes, the assignee, the status. A task
  reopened from done goes back to the top of the open list.
- **Move** an open task right after another one, or to the top.
- **Delete.** The task is hidden, not erased.
- **Sweep.** Deleted tasks are erased for good after the retention.

## The rules

- **Every write names the version it read.** A task carries a version
  number, and every edit, move, and delete says which version the
  caller saw. If the stored task has moved on, the write is refused
  and nothing is merged; the caller reads again. An edit that raced a
  delete finds the task gone and cannot bring it back.
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
