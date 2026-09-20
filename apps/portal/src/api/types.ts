// The facade: feature code imports these names and never a generated path.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type OrgView = Schemas["OrgView"];
export type UserView = Schemas["UserView"];
export type MeView = Schemas["MeView"];
export type MembershipView = Schemas["MembershipView"];
export type MembershipChoiceView = Schemas["MembershipChoiceView"];
export type LoginRequest = Schemas["LoginRequest"];
export type IssuedLoginView = Schemas["IssuedLoginView"];
export type ExchangeSessionRequest = Schemas["ExchangeSessionRequest"];
export type IssuedSessionView = Schemas["IssuedSessionView"];
export type ApiKeyView = Schemas["ApiKeyView"];
export type AddApiKeyRequest = Schemas["AddApiKeyRequest"];
export type IssuedApiKeyView = Schemas["IssuedApiKeyView"];
export type IssuedTicketView = Schemas["IssuedTicketView"];
export type TaskView = Schemas["TaskView"];
export type AddTaskRequest = Schemas["AddTaskRequest"];
export type UpdateTaskRequest = Schemas["UpdateTaskRequest"];
export type TaskPageView = Schemas["TaskPageView"];
export type MoveTaskRequest = Schemas["MoveTaskRequest"];
export type TaskStatus = Schemas["TaskStatus"];
export type TaskScope = Schemas["TaskScope"];
export type EventView = Schemas["EventView"];
export type Role = Schemas["Role"];
export type Permission = Schemas["Permission"];
