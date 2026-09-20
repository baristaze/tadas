import type { TaskView } from "../../api";
import { useState, type DragEvent } from "react";
import { Button, LinkButton, Pill, Select, TextArea, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import type { DropSide, TaskRow } from "./tasksModel";
import type { TaskEdit } from "./useTasksVm";

export interface DragProps {
  draggable: boolean;
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
      className={leaving ? "tadas-leaving" : arriving ? "tadas-arriving" : undefined}
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
      {/* The title keeps a readable width and wraps by words; when the row runs
          out of room, the pills and links move to a line of their own. */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: tokens.space.sm }}>
        <input
          type="checkbox"
          aria-label={row.done ? `Reopen ${row.title}` : `Mark ${row.title} done`}
          checked={struck}
          disabled={!canWrite || leaving}
          onChange={onToggle}
          style={{ width: 18, height: 18, flexShrink: 0, cursor: canWrite ? "pointer" : "default" }}
        />
        <span
          style={{
            flex: "1 1 8em",
            minWidth: 0,
            textDecoration: struck ? "line-through" : "none",
            color: struck ? tokens.color.muted : tokens.color.text,
            overflowWrap: "break-word",
          }}
        >
          {row.title}
        </span>
        <span
          style={{
            marginLeft: "auto",
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "flex-end",
            alignItems: "center",
            gap: tokens.space.sm,
          }}
        >
          <Pill title={`Created by ${row.createdBy}`}>· {row.createdBy}</Pill>
          {row.assignee ? <Pill title="Assigned to">assigned to {row.assignee}</Pill> : null}
          {canWrite && !leaving ? <LinkButton onClick={editing ? onCancelEdit : onEdit}>{editing ? "close" : "edit"}</LinkButton> : null}
          {drag ? (
            <span
              role="button"
              aria-label={`Drag to reorder ${row.title}`}
              title="Drag to reorder"
              onMouseDown={drag.onGrab}
              style={{ cursor: "grab", color: tokens.color.muted, userSelect: "none", padding: `0 ${tokens.space.xs}` }}
            >
              ⠿
            </span>
          ) : null}
        </span>
      </div>
      {editing ? <EditForm key={task.id} version={task.version} row={row} assigneeOptions={assigneeOptions} onSave={onSave} onCancel={onCancelEdit} onDelete={onDelete} /> : null}
    </li>
  );
}

function EditForm({
  version,
  row,
  assigneeOptions,
  onSave,
  onCancel,
  onDelete,
}: {
  version: number;
  row: TaskRow;
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
  return (
    <form
      className="tadas-arriving"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({ title, notes, assigneeId: assigneeId || null, version: draftVersion });
      }}
      style={{ display: "grid", gap: tokens.space.md, padding: `${tokens.space.md} 0 ${tokens.space.sm} 26px` }}
    >
      <TextField label="Title" value={title} onChange={setTitle} />
      <TextArea label="Notes" value={notes} onChange={setNotes} />
      <Select label="Assigned to" value={assigneeId} options={assigneeOptions} onChange={setAssigneeId} />
      <div style={{ display: "flex", gap: tokens.space.sm }}>
        <Button type="submit" disabled={!title.trim()}>
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
