import type { TaskView } from "../../api";
import { useState, type DragEvent } from "react";
import { Button, LinkButton, Pill, Select, TextArea, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { remindAtChange, toInputValue } from "./dueModel";
import type { DropSide, TaskRow } from "./tasksModel";
import type { TaskEdit } from "./useTasksVm";

/** The handle's column; every row keeps it, so the boxes line up in both groups. */
const HANDLE_WIDTH = 14;

export interface DragProps {
  draggable: boolean;
  dragging: boolean;
  dropIndicator: DropSide | null;
  onGrab: () => void;
  onDragStart: (event: DragEvent) => void;
  onDragOver: (event: DragEvent) => void;
  onDrop: (event: DragEvent) => void;
  onDragEnd: () => void;
}

export function TaskItem({
  task,
  row,
  leaving,
  listMountedAt,
  canWrite,
  editing,
  saving,
  assigneeOptions,
  drag,
  onToggle,
  onEdit,
  onCancelEdit,
  onSave,
  onDelete,
}: {
  task: TaskView;
  row: TaskRow;
  leaving: boolean;
  listMountedAt: number;
  canWrite: boolean;
  editing: boolean;
  saving: boolean;
  assigneeOptions: { value: string; label: string }[];
  drag?: DragProps;
  onToggle: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSave: (edit: TaskEdit) => void;
  onDelete: () => void;
}) {
  // A row that mounts after its list did is a task that just arrived: created
  // here, pushed from another tab, moved from the other group, or a new page.
  const [arriving] = useState(() => Date.now() - listMountedAt > 400);
  const struck = row.done || leaving;
  const indicator = drag?.dropIndicator;
  return (
    <li
      className={[leaving ? "tadas-leaving" : arriving ? "tadas-arriving" : "", drag?.dragging ? "tadas-dragging" : ""]
        .filter(Boolean)
        .join(" ") || undefined}
      draggable={drag?.draggable ?? false}
      onDragStart={drag?.onDragStart}
      onDragOver={drag?.onDragOver}
      onDrop={drag?.onDrop}
      onDragEnd={drag?.onDragEnd}
      style={{
        listStyle: "none",
        padding: `${tokens.space.sm} 0`,
        borderTop: `2px solid ${indicator === "before" ? tokens.color.accent : "transparent"}`,
        borderBottom:
          indicator === "after" ? `2px solid ${tokens.color.accent}` : `1px solid ${tokens.color.border}`,
        pointerEvents: leaving ? "none" : undefined,
      }}
    >
      {/* One line at any width: the title gives way first and ends in an
          ellipsis; the handle, the box, the pills, and the link keep their size. */}
      <div style={{ display: "flex", alignItems: "center", gap: tokens.space.sm }}>
        <span
          role={drag ? "button" : undefined}
          aria-label={drag ? `Drag to reorder ${row.title}` : undefined}
          aria-hidden={drag ? undefined : true}
          title={drag ? "Drag to reorder" : undefined}
          onMouseDown={drag?.onGrab}
          className={drag ? "tadas-handle" : undefined}
          style={{
            width: HANDLE_WIDTH,
            flexShrink: 0,
            textAlign: "center",
            cursor: drag ? "grab" : undefined,
            color: tokens.color.muted,
            userSelect: "none",
          }}
        >
          {drag ? "⠿" : null}
        </span>
        <input
          type="checkbox"
          aria-label={row.done ? `Reopen ${row.title}` : `Mark ${row.title} done`}
          checked={struck}
          disabled={!canWrite || leaving}
          onChange={onToggle}
          style={{ width: 18, height: 18, margin: 0, flexShrink: 0, cursor: canWrite ? "pointer" : "default" }}
        />
        <span
          className="tadas-task-title"
          title={row.notes ? `${row.title}\n\n${row.notes}` : row.title}
          onDoubleClick={canWrite && !leaving && !editing ? onEdit : undefined}
          style={{
            flex: "1 1 auto",
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            textDecoration: struck ? "line-through" : "none",
            color: struck ? tokens.color.muted : tokens.color.text,
          }}
        >
          {row.title}
          {row.notes ? <span style={{ color: tokens.color.muted }}> — {row.notes}</span> : null}
        </span>
        <Pill title={`Created by ${row.createdBy}`}>{row.createdBy}</Pill>
        {row.assignee ? (
          <Pill title={`Assigned to ${row.assignee}`} tone={row.assignee === "you" ? "accent" : "plain"}>
            for {row.assignee}
          </Pill>
        ) : null}
        {row.due ? (
          <Pill title={row.due.title} tone={row.done || row.due.state === "upcoming" ? "plain" : "danger"}>
            {row.due.text}
          </Pill>
        ) : null}
        {canWrite && !leaving ? (
          <LinkButton onClick={editing ? onCancelEdit : onEdit}>{editing ? "close" : "edit"}</LinkButton>
        ) : null}
      </div>
      {editing ? <EditForm key={task.id} version={task.version} remindAt={task.remind_at ?? null} row={row} saving={saving} assigneeOptions={assigneeOptions} onSave={onSave} onCancel={onCancelEdit} onDelete={onDelete} /> : null}
    </li>
  );
}

function EditForm({
  version,
  remindAt,
  row,
  saving,
  assigneeOptions,
  onSave,
  onCancel,
  onDelete,
}: {
  version: number;
  remindAt: string | null;
  row: TaskRow;
  saving: boolean;
  assigneeOptions: { value: string; label: string }[];
  onSave: (edit: TaskEdit) => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  // A draft belongs to the version first opened, even when realtime refreshes the row.
  const [draftVersion] = useState(version);
  const [title, setTitle] = useState(row.title);
  const [notes, setNotes] = useState(row.notes);
  const [assigneeId, setAssigneeId] = useState(row.assigneeId ?? "");
  // The due time as first opened: the edit sends it only when it changed.
  const [dueAtOpen] = useState(() => toInputValue(remindAt));
  const [due, setDue] = useState(dueAtOpen);
  return (
    <form
      className="tadas-arriving"
      onSubmit={(event) => {
        event.preventDefault();
        const change = remindAtChange(dueAtOpen, due);
        onSave({
          title,
          notes,
          assigneeId: assigneeId || null,
          version: draftVersion,
          ...(change !== undefined ? { remindAt: change } : {}),
        });
      }}
      style={{ display: "grid", gap: tokens.space.md, padding: `${tokens.space.md} 0 ${tokens.space.sm} ${HANDLE_WIDTH + 18 + 16}px` }}
    >
      <TextField label="Title" value={title} onChange={setTitle} />
      <TextArea label="Notes" value={notes} onChange={setNotes} />
      <Select label="Assigned to" value={assigneeId} options={assigneeOptions} onChange={setAssigneeId} />
      <div style={{ display: "flex", gap: tokens.space.sm, alignItems: "end" }}>
        <TextField label="Due (your local time)" type="datetime-local" value={due} onChange={setDue} />
        {due ? <LinkButton onClick={() => setDue("")}>clear due time</LinkButton> : null}
      </div>
      <div style={{ display: "flex", gap: tokens.space.sm }}>
        {/* The draft names the version it was opened at, so a second submit
            of the same draft would be refused as someone else's change. */}
        <Button type="submit" disabled={!title.trim() || saving}>
          Save
        </Button>
        <Button tone="plain" onClick={onCancel}>
          Cancel
        </Button>
        <span style={{ marginLeft: "auto" }}>
          <Button tone="danger" onClick={onDelete}>
            Delete
          </Button>
        </span>
      </div>
    </form>
  );
}
