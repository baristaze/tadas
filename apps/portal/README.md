# Tadas portal

The browser app a signed-in person uses: React, TypeScript, Vite, TanStack
Query, and Zustand. It holds the shell every product screen sits in:
sign-in, the org chip and switch, settings, and one realtime channel.

## Layout

- `@tadas/client`, from [clients/typescript/](../../clients/typescript/README.md):
  the one transport client and the types generated from the API's document.
  The portal calls `fetch` nowhere and never reads the generated schema.
- `src/app/`: routes, the nav, the query cache, the session, and the one
  client instance the app shares.
- `src/features/<name>/`: one folder per screen, a pure model, a
  view-model hook, and a page. `tasks/` is the product's first screen, at
  `/`, with `attachments/`, `imports/`, and `billing/` beside it.
- `src/queries/`: query keys and hooks, one file per API namespace.
  `flags.ts` reads the session's flags as one snapshot from the API, and a
  view-model reads a flag with `useFlag`. No flag vendor's SDK is in the
  bundle.
- `src/realtime/`: the socket and its router. A push about a user reads
  that one member and places it (`hints.ts`), and so does a push about a
  task (`queries/taskCache.ts`); any other push invalidates the queries of
  its entity.
- `src/store/`, `src/design/`: client state and the design kit.

## The product's screens

- Tasks. Adding one is a single text box: type the title and press Enter,
  or click Add. The due date is set by editing the task, with a date
  picker and a link that clears it. A due date is a date, never a time:
  the row says "due Today", "due Tomorrow", "due Fri" within the week
  ahead, or "due Sep 30" further out, and "Overdue" once the day has
  passed with no reminder out. The reminder goes out at nine in the
  morning of the date, in the time zone of the person the task is for.
- The tasks page's heading is the list on screen. When the org has more
  than one member, of either kind, it is a switch, My tasks | Team. When
  the person is alone in the org it is "My tasks", with no switch, and
  the page shows the `mine` list, which the server's rule (a task
  assigned to the person, or unassigned and made by them) makes every
  task of an org of one. A saved Team pick holds only where the switch
  shows. The count is the member list the rows already name people
  from, read whole, so it costs no read of its own (`scopeModel.ts`).
- The tasks page's two sections, Open and Done, fold under their titles.
  The title is a button (`aria-expanded`), so a click, Enter, or Space
  folds it, and the caret turns with it. Open starts unfolded and Done
  folded; after that each section stays as the person left it, per org,
  in the preferences (`folded`). The archive folds with Done.
- Many tasks at once (`src/features/tasks/`: `selectionModel.ts` and
  `bulkModel.ts` are pure, `useBulkVm.ts` decides). ⌘-click (Ctrl-click)
  adds a row to the selection or drops it, Shift-click reaches from the
  row picked last, and on touch a finger resting on a row for half a
  second picks it. Once a selection is open, a plain click or tap picks
  too. From the keyboard, each list is a grid with one tab stop: the
  arrows move between rows, Space picks, and Shift reaches. Escape lets
  the selection go. A selected row is tinted, with `aria-selected`; its
  box still means done or open and is never a second box. A selection
  lives in one section of the list on screen; a pick in the other
  section starts over there, and a switch of scope or org starts with
  none. There is no drag to select, since dragging a row reorders the
  open list. While anything is selected, a bar at the foot of the window
  says how many and offers the one action that applies: Mark done for
  open tasks, Reopen for done ones. Each section's ⋯ menu (the kit's
  `Menu`) has Select all, which selects every task of the section in the
  scope, loaded or not, counted on the server (`GET /v1/tasks/count`),
  and, in red, "Mark all as done…" on Open and "Reopen all…" on Done,
  which ask first with that count. Every change is one call,
  `POST /v1/tasks/bulk`, under an idempotency key: the rows move at once,
  and the lists are read again when the server answers, since the answer
  names ids. A toast then says what changed, with Undo for ten seconds;
  Undo is the other action over exactly the ids the answer named, sent
  bottom first for a reopen, so the list reads as it did. A change of
  more tasks than the answer names (a thousand) offers no Undo. A reopen
  past the plan's active tasks changes what it can and opens the upgrade
  dialog for the rest. The toast is the notices store's (`notices.ts`,
  its `done` tone and its one action), drawn with the kit's `Toast`.
- The task lists are written, not read again. A write answers with the
  task as the server wrote it, and that answer goes into every cached
  list, in every scope, at once (`src/queries/taskCache.ts`). A live
  push about a task names its id and the version its change wrote, never
  a field. A tab that already placed the task at that version reads
  nothing: the tab that made the write holds its answer, and the push is
  about that answer. Any other tab reads that one task
  (`GET /v1/tasks/{id}`) and places it the same way; a 404 takes it
  out. A push that names no version (the reminder, the daily archive)
  is always read (ADR 0061). Where it goes is one pure function
  (`src/queries/taskPlacement.ts`): the open list by rank then id, the
  done list newest first, the `mine` scope by the server's rule,
  archived and deleted tasks in neither. A list is the window the page
  loaded, and its last row is the one the next page's cursor names: a
  task that sorts past it is left out, and a change the window cannot
  answer (a removal that leaves a window with more behind it short, the
  last row moving) reads that one list again. A task placed into a full
  window stays held past what the page shows, and shows on Show more. An
  answer older than one already placed is dropped, by the task's
  version. Pushes are gathered until 100 ms pass without one, and for
  500 ms at most (`src/realtime/hints.ts`): a task pushed twice is
  read once, and past twenty tasks in one window (an import step, a bulk
  change, the sweep's respace of a run of ranks) the lists are read once
  instead. Whether a task is held is asked when the window closes, so
  the push of a tab's own write that beats the write's answer is still
  skipped, and only the tasks left to read count toward the twenty.
- A record read back from the stream (a replay, the first catch-up) is
  routed once per task, through the same reader, and once per entity for
  an entity no reader reads. A reminder is a notice on the channel
  (ADR 0096), told once, as the cursor passes it: a live one as its push
  arrives, and one read back whatever record of its task follows it,
  once the read-back ends. What one read-back hands over is announced
  each by its title up to three, and past three in one notice that
  counts them, "You missed 5 reminders while you were away"
  (`reminder.ts`, ADR 0075).
- A task's files are `src/features/attachments/`, shown in the task's
  open view: dropped or picked, started on the API, posted straight to
  the store, confirmed, listed with name, size, and type, downloaded and
  saved under the file's own name, removed. Each file with a preview
  shows it inline, through the store's short-lived inline link: an image
  as a thumbnail that opens larger in the page, a video and a sound in
  the browser's player, a PDF in a frame; anything else (text, documents,
  archives) is download-only, and download stays beside every preview.
  Someone who cannot write opens a task's files read-only with its
  `files` link. The flows (`transfer.ts`) take their effects as
  arguments and run in a test without React. Where the store cannot
  take a form, the bytes go through the API instead.
- An import is `src/features/imports/`: the tasks page's Import action (a
  button of its own beside the page's heading; the quick-add form stays one
  text box) opens a small dialog that picks a CSV file. The file goes up
  the way an attachment does (`importFlow.ts`, its effects handed in), and
  the import starts naming it. The rows are read in the worker; the page
  follows the org's newest import by what the channel pushes
  (`orchestrations.orchestration.updated`, whose entity keys
  `queries/imports.ts`), with no polling: a progress line (created N of M,
  skipped K), and when the import parks on the plan's active tasks, the
  one upgrade dialog and Resume. An import that ended shows what it did
  until dismissed. Under the done list, "Show archived" opens the done
  tasks the daily cleanup archived (`ArchivedTasks.tsx`), each with
  Restore.
- A write refused for a plan's bound opens the upgrade dialog instead of
  a notice (`src/store/upgrade.ts`, opened from the query cache's one
  mutation error hook and rendered once by
  `src/features/billing/UpgradeDialog.tsx`). The org chip shows the plan.
  Settings and Billing open with "← Tasks" above their title, the way
  back to the list, and Settings holds the org's Slack app.
- "Former member". A task names its maker and its assignee from the
  org's member list, read whole; an id the list does not hold is a
  person who left the org or deleted their account, and reads "Former
  member" (`tasksModel.nameOf`).

## Run

```bash
pnpm --filter @tadas/portal dev    # http://localhost:5173, /v1 goes to 127.0.0.1:8000
pnpm --filter @tadas/portal test
make openapi                      # regenerates the client's types
```

On the local stack, `/login/dev` signs in by address alone.
