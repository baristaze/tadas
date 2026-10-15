// The tasks namespace's types: an org's tasks, their order and their bulk
// actions, and the imports that bring tasks in. An app names each as
// tasks.<Name>, through the package's entry.
import type { components } from "../schema/tasks";

type Schemas = components["schemas"];

export type TaskView = Schemas["TaskView"];
export type AddTaskRequest = Schemas["AddTaskRequest"];
export type UpdateTaskRequest = Schemas["UpdateTaskRequest"];
export type TaskPageView = Schemas["TaskPageView"];
export type MoveTaskRequest = Schemas["MoveTaskRequest"];
export type RestoreTaskRequest = Schemas["RestoreTaskRequest"];
export type BulkAction = Schemas["BulkAction"];
export type BulkTasksRequest = Schemas["BulkTasksRequest"];
export type BulkTasksView = Schemas["BulkTasksView"];
export type SkipReason = Schemas["SkipReason"];
export type TaskCountView = Schemas["TaskCountView"];
export type StartImportRequest = Schemas["StartImportRequest"];
export type ImportView = Schemas["ImportView"];
export type ImportPageView = Schemas["ImportPageView"];
export type TaskStatus = Schemas["TaskStatus"];
export type TaskScope = Schemas["TaskScope"];
