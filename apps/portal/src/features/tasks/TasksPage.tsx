import type { TaskScope } from "../../api";
import { useState, type DragEvent } from "react";
import { AppNav } from "../../app/AppNav";
import { Banner, Button, Card, LinkButton, Muted, Page, SegmentedControl } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { TaskItem } from "./TaskItem";
import type { DropSide } from "./tasksModel";
import { useTasksVm, type TasksVm } from "./useTasksVm";

const SCOPES: { value: TaskScope; label: string }[] = [
  { value: "mine", label: "My Tasks" },
  { value: "team", label: "Team's Tasks" },
];

export function TasksPage() {
  const vm = useTasksVm();
  return (
    <Page title="Tasks" nav={<AppNav />}>
      <div style={{ display: "flex", alignItems: "center", gap: tokens.space.md }}>
        <SegmentedControl label="Which tasks" value={vm.scope} options={SCOPES} onChange={vm.setScope} />
      </div>
      {vm.error ? (
        <Banner>
          {vm.error} <LinkButton onClick={vm.dismissError}>dismiss</LinkButton>
        </Banner>
      ) : null}
      {vm.canWrite ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void vm.add();
          }}
          style={{ display: "flex", gap: tokens.space.sm }}
        >
          <input
            aria-label="New task"
            placeholder="Add a task, e.g. migrate DB"
            value={vm.title}
            onChange={(event) => vm.setTitle(event.target.value)}
            maxLength={500}
            style={{
              flex: 1,
              font: "inherit",
              fontSize: tokens.font.size.md,
              padding: tokens.space.sm,
              border: `1px solid ${tokens.color.border}`,
              borderRadius: tokens.radius.sm,
            }}
          />
          <Button type="submit" disabled={!vm.title.trim() || vm.adding}>
            Add
          </Button>
        </form>
      ) : null}
      {vm.loading ? (
        <Muted>Loading</Muted>
      ) : (
        // Keyed by scope: switching lists mounts fresh rows without the arrival motion.
        <TaskGroups key={vm.scope} vm={vm} />
      )}
    </Page>
  );
}

function TaskGroups({ vm }: { vm: TasksVm }) {
  const [listMountedAt] = useState(() => Date.now());
  const [grabbedId, setGrabbedId] = useState<string | null>(null);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [over, setOver] = useState<{ id: string; side: DropSide } | null>(null);

  const endDrag = () => {
    setGrabbedId(null);
    setDraggedId(null);
    setOver(null);
  };

  const itemProps = (entry: TasksVm["open"][number]) => ({
    task: entry.task,
    row: entry.row,
    leaving: entry.leaving,
    listMountedAt,
    canWrite: vm.canWrite,
    editing: vm.editingId === entry.task.id,
    assigneeOptions: vm.assigneeOptions,
    onEdit: () => vm.startEditing(entry.task.id),
    onCancelEdit: vm.stopEditing,
    onSave: (edit: Parameters<TasksVm["save"]>[1]) => void vm.save(entry.task, edit),
    onDelete: () => vm.destroy(entry.task),
  });

  return (
    <>
      <Card title={`Open (${vm.open.filter((e) => !e.leaving).length})`}>
        {vm.open.length === 0 ? <Muted>Nothing open. Add a task above.</Muted> : null}
        <ul style={{ margin: 0, padding: 0 }}>
          {vm.open.map((entry) => (
            <TaskItem
              key={entry.task.id}
              {...itemProps(entry)}
              onToggle={() => void vm.complete(entry.task)}
              drag={
                vm.canWrite && !entry.leaving
                  ? {
                      draggable: grabbedId === entry.task.id,
                      dropIndicator: over?.id === entry.task.id && draggedId !== entry.task.id ? over.side : null,
                      onGrab: () => setGrabbedId(entry.task.id),
                      onDragStart: (event: DragEvent) => {
                        event.dataTransfer.effectAllowed = "move";
                        event.dataTransfer.setData("text/plain", entry.task.id);
                        setDraggedId(entry.task.id);
                      },
                      onDragOver: (event: DragEvent) => {
                        if (!draggedId) return;
                        event.preventDefault();
                        const box = event.currentTarget.getBoundingClientRect();
                        const side: DropSide = event.clientY < box.top + box.height / 2 ? "before" : "after";
                        if (over?.id !== entry.task.id || over.side !== side) setOver({ id: entry.task.id, side });
                      },
                      onDrop: (event: DragEvent) => {
                        event.preventDefault();
                        if (draggedId && over) vm.drop(draggedId, over.id, over.side);
                        endDrag();
                      },
                      onDragEnd: endDrag,
                    }
                  : undefined
              }
            />
          ))}
        </ul>
        {vm.hasMoreOpen ? (
          <div style={{ paddingTop: tokens.space.md }}>
            {vm.loadingMoreOpen ? <Muted>Loading</Muted> : <LinkButton onClick={vm.showMoreOpen}>Show more</LinkButton>}
          </div>
        ) : null}
      </Card>
      <Card title="Done">
        {vm.done.length === 0 ? <Muted>Nothing done yet.</Muted> : null}
        <ul style={{ margin: 0, padding: 0 }}>
          {vm.done.map((entry) => (
            <TaskItem key={entry.task.id} {...itemProps(entry)} onToggle={() => void vm.reopen(entry.task)} />
          ))}
        </ul>
        {vm.hasMoreDone ? (
          <div style={{ paddingTop: tokens.space.md }}>
            {vm.loadingMoreDone ? <Muted>Loading</Muted> : <LinkButton onClick={vm.showMoreDone}>Show more</LinkButton>}
          </div>
        ) : null}
      </Card>
    </>
  );
}
