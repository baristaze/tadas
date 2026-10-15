// The billing namespace's types: an org's plan, its limits and usage, and the
// checkout and portal it opens. An app names each as billing.<Name>, through
// the package's entry.
import type { components } from "../schema/billing";

type Schemas = components["schemas"];

export type Plan = Schemas["Plan"];
export type PlanLimitsView = Schemas["PlanLimitsView"];
export type PlanOfferView = Schemas["PlanOfferView"];
export type BillingView = Schemas["BillingView"];
export type StartCheckoutRequest = Schemas["StartCheckoutRequest"];
export type OpenPortalRequest = Schemas["OpenPortalRequest"];
export type RedirectView = Schemas["RedirectView"];
