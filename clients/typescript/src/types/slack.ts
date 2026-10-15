// The slack namespace's types: an org's one Slack installation and how it is
// started. An app names each as slack.<Name>, through the package's entry.
import type { components } from "../schema/slack";

type Schemas = components["schemas"];

export type SlackInstallationView = Schemas["SlackInstallationView"];
export type SlackInstallationStatus = Schemas["SlackInstallationStatus"];
export type SlackStatusView = Schemas["SlackStatusView"];
export type SlackInstallStartView = Schemas["SlackInstallStartView"];
