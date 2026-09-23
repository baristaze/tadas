import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { MembershipChoiceView } from "../api";
import { useBilling } from "../queries/billing";
import { useMe, useMyMemberships, useSwitchOrg } from "../queries/tenancy";
import { useNoticesStore } from "../store/notices";
import { adoptSession } from "./adoptSession";
import { planName } from "../features/billing/billingModel";
import { chipChoices } from "./orgChipModel";
import { switchOrg } from "./switchOrg";

export function useOrgChipVm() {
  const navigate = useNavigate();
  const me = useMe();
  const memberships = useMyMemberships();
  const exchange = useSwitchOrg();
  // The plan badge is a courtesy: the chip works the same when billing fails to load.
  const billing = useBilling();
  const notify = useNoticesStore((s) => s.notify);
  const [open, setOpen] = useState(false);
  const choices = chipChoices(memberships.isPending ? undefined : memberships.data, me.data?.org.id);

  const pick = async (membership: MembershipChoiceView) => {
    setOpen(false);
    const outcome = await switchOrg({
      exchange: () => exchange.mutateAsync(membership.org.id),
      adopt: adoptSession,
      report: notify,
    });
    // The new tenant starts on its task list; a page of the old one may not exist here.
    if (outcome === "switched") navigate("/", { replace: true });
  };

  return {
    orgName: me.data?.org.name ?? "Tadas",
    plan: billing.data ? planName(billing.data.plan) : null,
    role: me.data?.role,
    canSwitch: choices.canSwitch,
    others: choices.others,
    open,
    switching: exchange.isPending,
    toggle: () => setOpen((value) => choices.canSwitch && !value),
    close: () => setOpen(false),
    pick,
  };
}
